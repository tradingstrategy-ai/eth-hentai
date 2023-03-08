"""Enzyme protocol deployment.

Functions to fetch live on-chain Enzyme deployment or deploy your own unit testing version.
"""
import enum
import re
from dataclasses import dataclass, field
from pprint import pformat
from typing import Dict, Tuple

from web3._utils.events import EventLogErrorFlags

from eth_defi.abi import get_contract, encode_with_signature, get_deployed_contract
from eth_defi.deploy import deploy_contract
from eth_typing import HexAddress
from web3 import Web3
from web3.contract import Contract

from eth_defi.revert_reason import fetch_transaction_revert_reason


class RateAsset(enum.Enum):
    """See IChainlinkPriceFeedMixin.sol"""
    ETH = 0
    USD = 1


class EnzymeDeploymentError(Exception):
    """Something is not so right."""


@dataclass(slots=True)
class EnzymeContracts:
    """Manage the registry of Enzyme contracts.

    Mimics Deployer.sol.
    """
    web3: Web3
    deployer: HexAddress
    dispatcher: Contract = None
    external_position_factory: Contract = None
    protocol_fee_reserve_lib: Contract = None
    protocol_fee_reserve_proxy: Contract = None
    address_list_registry: Contract = None
    fund_deployer: Contract = None
    value_interpreter: Contract = None
    policy_manager: Contract = None
    external_position_manager: Contract = None
    fee_manager: Contract = None
    integration_manager: Contract = None
    comptroller_lib: Contract = None
    protocol_fee_tracker: Contract = None
    vault_lib: Contract = None
    gas_relay_paymaster_lib: Contract = None
    gas_relay_paymaster_factory: Contract = None

    def deploy(self, contract_name: str, *args):
        """Deploys a contract and stores its reference.

        Pick ABI JSON file from our precompiled package.
        """
        # Convert to snake case
        # https://stackoverflow.com/a/1176023/315168
        var_name = re.sub(r'(?<!^)(?=[A-Z])', '_', contract_name).lower()
        contract = deploy_contract(self.web3, f"enzyme/{contract_name}.json", self.deployer, *args)
        setattr(self, var_name, contract)

    def get_deployed_contract(self, contract_name: str, address: HexAddress) -> Contract:
        """Helper access for IVault and IComptroller"""
        contract = get_deployed_contract(self.web3, f"enzyme/{contract_name}.json", address)
        return contract


@dataclass(slots=True)
class EnzymeDeployment:
    """Enzyme protocol deployment description.

    - Describe on-chain Enzyme deployment

    - Provide property access and documentation of different parts of Enzyme protocol

    - Allow vault deployments and such
    """

    #: Web3 connection this deployment is tied to
    web3: Web3

    #: The deployer account used in tests
    deployer: HexAddress

    #: Mimic Enzyme's deployer.sol
    contracts: EnzymeContracts

    #: MELON ERC-20
    mln: Contract

    #: WETH ERC-20
    weth: Contract

    def add_primitive(
            self,
            token: Contract,
            aggregator: Contract,
            rate_asset: RateAsset,
        ):
        """Add a primitive asset to a Enzyme protocol.

        This will tell Enzyme how to value this asset.

        - See ValueInterpreter.sol

        - See ChainlinkPriceFeedMixin.sol
        """

        assert isinstance(rate_asset, RateAsset)
        assert token.functions.decimals().call() >= 6
        latest_round_data = aggregator.functions.latestRoundData().call()
        assert len(latest_round_data) == 5

        value_interpreter = self.contracts.value_interpreter
        primitives = [token.address]
        aggregators = [aggregator.address]
        rate_assets = [rate_asset.value]
        value_interpreter.functions.addPrimitives(primitives, aggregators, rate_assets).transact({"from": self.deployer})

    def create_new_vault(
            self,
            owner: HexAddress,
            denomination_asset: Contract,
            fund_name = "Example Fund",
            fund_symbol = "EXAMPLE",
            shares_action_time_lock: int = 0,
            fee_manager_config_data = b"",
            policy_manager_config_data = b"",
    ) -> Tuple[Contract, Contract]:
        """
        Creates a new fund (vault).

        - See `CreateNewVault.sol`.

        - See `FundDeployer.sol`.

        :return:
            Tuple (Comptroller contract, vault contract)
        """

        fund_deployer = self.contracts.fund_deployer
        tx_hash = fund_deployer.functions.createNewFund(
            owner,
            fund_name,
            fund_symbol,
            denomination_asset.address,
            shares_action_time_lock,
            fee_manager_config_data,
            policy_manager_config_data,
        ).transact({
            "from": self.deployer,
        })
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt["status"] != 1:
            reason = fetch_transaction_revert_reason(self.web3, tx_hash)
            raise EnzymeDeploymentError(f"createNewFund() failed: {reason}")

        events = list(self.contracts.fund_deployer.events.NewFundCreated().process_receipt(receipt, EventLogErrorFlags.Discard))
        assert len(events) == 1
        new_fund_created_event = events[0]
        comptroller_proxy = new_fund_created_event["args"]["comptrollerProxy"]
        vault_proxy = new_fund_created_event["args"]["vaultProxy"]

        comptroller_contract = self.contracts.get_deployed_contract("ComptrollerLib", comptroller_proxy)
        vault_contract = self.contracts.get_deployed_contract("VaultLib", vault_proxy)
        return comptroller_contract, vault_contract

    @staticmethod
    def deploy_core(
            web3: Web3,
            deployer: HexAddress,
            mln: Contract,
            weth: Contract,
            chainlink_stale_rate_threshold = 3650 * 24 * 3600,  # 10 years
            vault_position_limit = 20,
            vault_mln_burner = "0x0000000000000000000000000000000000000000",
    ) -> "EnzymeDeployment":
        """Make a test Enzyme deployment.

        Designed to be used in unit testing.

        This is copied from the Forge test suite `deployLiveRelease()`.
        
        See
        
        - contracts/enzyme/tests/deployment
        
        :param deployer:
            EVM account used for the deployment
            
        """

        weth_address = weth.address
        mln_address = mln.address

        contracts = EnzymeContracts(web3, deployer)

        def _deploy_persistent():
            # Mimic deployPersistentContracts()
            contracts.deploy("Dispatcher")
            contracts.deploy("ExternalPositionFactory", contracts.dispatcher.address)
            contracts.deploy("ProtocolFeeReserveLib", contracts.dispatcher.address)

            # deployProtocolFeeReserveProxy()
            construct_data = encode_with_signature("init(address)", [contracts.dispatcher.address])
            contracts.deploy("ProtocolFeeReserveProxy", construct_data, contracts.protocol_fee_reserve_lib.address)
            contracts.deploy("AddressListRegistry", contracts.dispatcher.address)

            contracts.deploy("GasRelayPaymasterLib", weth_address, "0x0000000000000000000000000000000000000000", "0x0000000000000000000000000000000000000000")
            contracts.deploy("GasRelayPaymasterFactory", contracts.dispatcher.address, contracts.gas_relay_paymaster_lib.address)

        def _deploy_release_contracts():
            # Mimic deployReleaseContracts()
            contracts.deploy("FundDeployer", contracts.dispatcher.address, contracts.gas_relay_paymaster_factory.address)
            contracts.deploy("ValueInterpreter", contracts.fund_deployer.address, weth_address, chainlink_stale_rate_threshold)
            contracts.deploy("PolicyManager", contracts.fund_deployer.address, contracts.gas_relay_paymaster_factory.address)
            contracts.deploy("ExternalPositionManager", contracts.fund_deployer.address, contracts.external_position_factory.address, contracts.policy_manager.address)
            contracts.deploy("FeeManager", contracts.fund_deployer.address)
            contracts.deploy("IntegrationManager", contracts.fund_deployer.address, contracts.policy_manager.address, contracts.value_interpreter.address)
            contracts.deploy("ComptrollerLib",
                             contracts.dispatcher.address,
                             contracts.protocol_fee_reserve_proxy.address,
                             contracts.fund_deployer.address,
                             contracts.value_interpreter.address,
                             contracts.external_position_manager.address,
                             contracts.fee_manager.address,
                             contracts.integration_manager.address,
                             contracts.policy_manager.address,
                             contracts.gas_relay_paymaster_factory.address,
                             mln_address,
                             weth_address,
                             )
            contracts.deploy("ProtocolFeeTracker", contracts.fund_deployer.address)
            contracts.deploy("VaultLib",
                             contracts.external_position_manager.address,
                             contracts.gas_relay_paymaster_factory.address,
                             contracts.protocol_fee_reserve_proxy.address,
                             contracts.protocol_fee_tracker.address,
                             mln_address,
                             vault_mln_burner,
                             weth_address,
                             vault_position_limit
                             )

        def _set_fund_deployer_pseudo_vars():
            # Mimic setFundDeployerPseudoVars()
            contracts.fund_deployer.functions.setComptrollerLib(contracts.comptroller_lib.address).transact({"from": deployer})
            contracts.fund_deployer.functions.setProtocolFeeTracker(contracts.protocol_fee_tracker.address).transact({"from": deployer})
            contracts.fund_deployer.functions.setVaultLib(contracts.vault_lib.address).transact({"from": deployer})

        def _set_external_position_factory_position_deployers():
            # Mimic setExternalPositionFactoryPositionDeployers
            deployers = [contracts.external_position_manager.address]
            contracts.external_position_factory.functions.addPositionDeployers(deployers).transact({"from": deployer})

        def _set_release_live():
            # Mimic setReleaseLive()
            contracts.fund_deployer.functions.setReleaseLive().transact({"from": deployer})
            contracts.dispatcher.functions.setCurrentFundDeployer(contracts.fund_deployer.address).transact({"from": deployer})

        _deploy_persistent()
        _deploy_release_contracts()
        _set_fund_deployer_pseudo_vars()
        _set_external_position_factory_position_deployers()
        _set_release_live()

        # Some sanity checks
        assert contracts.gas_relay_paymaster_factory.functions.getCanonicalLib().call() != "0x0000000000000000000000000000000000000000"
        assert contracts.fund_deployer.functions.getOwner().call() == deployer
        assert contracts.value_interpreter.functions.getOwner().call() == deployer
        assert contracts.fund_deployer.functions.releaseIsLive().call() is True

        return EnzymeDeployment(
            web3,
            deployer,
            contracts,
            mln,
            weth,
        )