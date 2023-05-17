"""Deploy Enzyme protcol v4.

Based on https://github.com/enzymefinance/protocol/blob/v4/packages/protocol/tests/release/e2e/FundManagementWalkthrough.test.ts
"""
import pytest
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_typing import HexAddress, ChecksumAddress
from web3 import Web3
from web3.contract import Contract

from eth_defi.deploy import deploy_contract
from eth_defi.enzyme.deployment import EnzymeDeployment, RateAsset
from eth_defi.enzyme.vault import Vault
from eth_defi.event_reader.reader import extract_events
from eth_defi.middleware import construct_sign_and_send_raw_middleware_anvil
from eth_defi.token import TokenDetails
from eth_defi.trace import assert_transaction_success_with_explanation
from eth_defi.usdc.deployment import deploy_fiat_token
from eth_defi.usdc.tranfer_with_authorization import make_receive_with_authorization_transfer


@pytest.fixture()
def usdc(web3, deployer: ChecksumAddress) -> TokenDetails:
    """Centre fiat token.

    Deploy real USDC code.
    """
    return deploy_fiat_token(web3, deployer)


@pytest.fixture
def user(web3, deployer, usdc) -> LocalAccount:
    """Create a LocalAccount user.

    See limitations in `transfer_with_authorization`.
    """
    account = Account.create()
    stash = web3.eth.get_balance(deployer)
    tx_hash = web3.eth.send_transaction({"from": deployer, "to": account.address, "value": stash // 2})
    assert_transaction_success_with_explanation(web3, tx_hash)
    usdc.contract.functions.transfer(
        account.address,
        500 * 10**6,
    ).transact({"from": deployer})
    web3.middleware_onion.add(construct_sign_and_send_raw_middleware_anvil(account))
    return account


def test_enzyme_usdc_payment_forwarder(
    web3: Web3,
    deployer: HexAddress,
    user: LocalAccount,
    weth: Contract,
    mln: Contract,
    usdc: TokenDetails,
    usdc_usd_mock_chainlink_aggregator: Contract,
):
    """Buy shares using USDC payment forwader."""

    deployment = EnzymeDeployment.deploy_core(
        web3,
        deployer,
        mln,
        weth,
    )

    # Create a vault for user 1
    # where we nominate everything in USDC
    deployment.add_primitive(
        usdc.contract,
        usdc_usd_mock_chainlink_aggregator,
        RateAsset.USD,
    )

    comptroller, vault = deployment.create_new_vault(
        deployer,
        usdc.contract,
    )

    assert comptroller.functions.getDenominationAsset().call() == usdc.address
    assert vault.functions.getTrackedAssets().call() == [usdc.address]

    payment_forwarder = deploy_contract(
        web3,
        "VaultUSDCPaymentForwarder.json",
        deployer,
        usdc.address,
        comptroller.address,
    )

    block = web3.eth.get_block("latest")

    # The transfer will expire in one hour
    # in the test EVM timeline
    valid_before = block["timestamp"] + 3600

    # Construct bounded ContractFunction instance
    # that will transact with MockEIP3009Receiver.deposit()
    # smart contract function.
    bound_func = make_receive_with_authorization_transfer(
        token=usdc,
        from_=user,
        to=payment_forwarder.address,
        func=payment_forwarder.functions.buySharesOnBehalf,
        value=500 * 10**6,  # 500 USD,
        valid_before=valid_before,
        extra_args=(1,),  # minSharesQuantity
    )

    # Sign and broadcast the tx
    tx_hash = bound_func.transact(
        {
            "from": user.address,
            "gas": 5_000_000,
        }
    )

    # Print out Solidity stack trace if this fails
    assert_transaction_success_with_explanation(web3, tx_hash)

    assert payment_forwarder.functions.amountProxied().call() == 500 * 10**6  # Got shares

    vault = Vault(vault, comptroller, deployment)
    assert vault.get_gross_asset_value() == 500 * 10**6  # Vault has been funded
    assert vault.vault.functions.balanceOf(user.address).call() == 500 * 10**18  # Got shares
