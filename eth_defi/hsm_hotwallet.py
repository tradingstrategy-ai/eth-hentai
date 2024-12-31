"""HSM wallet management utilities.

- Create Google Cloud HSM-backed wallets with automatic environment configuration
- Sign transactions securely using Cloud HSM
- Support batched transaction signing with nonce management
"""

from decimal import Decimal
from typing import Optional, Any
import logging

from eth_typing import HexAddress
from web3 import Web3
from web3._utils.contracts import prepare_transaction
from web3.contract.contract import ContractFunction
from web3_google_hsm import GCPKmsAccount
from web3_google_hsm.config import BaseConfig
from web3_google_hsm.types import Transaction as Web3HSMTransaction

from eth_defi.basewallet import BaseWallet
from eth_defi.gas import apply_gas, estimate_gas_fees
from eth_defi.hotwallet import SignedTransactionWithNonce


logger = logging.getLogger(__name__)


class HSMWallet(BaseWallet):
    """HSM-backed wallet for secure transaction signing.

    - An HSM wallet uses a Google Cloud KMS key for secure key management and transaction signing,
      providing enhanced security compared to plaintext private keys

    - It is able to sign transactions, including batches, using manual nonce management.
      See :py:meth:`sync_nonce`, :py:meth:`allocate_nonce` and :py:meth:`sign_transaction_with_new_nonce`

    - Signed transactions carry extra debug information with them in :py:class:`SignedTransactionWithNonce`

    - Configuration can be provided either through environment variables or explicitly in the constructor

    Example using environment variables:

    .. code-block:: python

            # Assumes required environment variables are set:
            # GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_REGION, KEY_RING,
            # KEY_NAME, GOOGLE_APPLICATION_CREDENTIALS
            from web3 import Web3
            from eth_defi.trace import assert_transaction_success_with_explanation

            web3 = Web3(Web3.HTTPProvider('http://localhost:8545'))
            wallet = HSMWallet()  # Uses env vars for configuration
            wallet.sync_nonce(web3)

            # Send a simple ETH transfer
            tx = {
                "to": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "from": wallet.address,
                "value": web3.to_wei(0.1, "ether"),
                "gas": 21000,
                "gasPrice": web3.eth.gas_price,
                "chainId": web3.eth.chain_id,
                "data": "0x",
            }

            signed_tx = wallet.sign_transaction_with_new_nonce(tx)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            assert_transaction_success_with_explanation(web3, tx_hash)

    Example with explicit configuration(Not Recommended):

    .. code-block:: python

            from web3_google_hsm.config import BaseConfig

            config = BaseConfig(
                project_id='my-project',
                location_id='us-east1',
                key_ring_id='eth-keys',
                key_id='signing-key'
            )

            wallet = HSMWallet(config=config)
            wallet.sync_nonce(web3)

            # Use with contract interactions
            usdc_contract = web3.eth.contract(address=usdc_address, abi=usdc_abi)
            transfer_amount = 500 * 10**6  # 500 USDC

            signed_tx = wallet.transact_with_contract(
                usdc_contract.functions.transfer,
                recipient_address,
                transfer_amount
            )
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            assert_transaction_success_with_explanation(web3, tx_hash)

    Required environment variables if no config provided:
        - GOOGLE_CLOUD_PROJECT: GCP project ID
        - GOOGLE_CLOUD_REGION: GCP region (e.g., us-east1)
        - KEY_RING: Name of the key ring in Cloud KMS
        - KEY_NAME: Name of the key in the key ring
        - GOOGLE_APPLICATION_CREDENTIALS: Path to service account credentials JSON

    .. note::

        This class is not thread safe. If multiple threads try to sign transactions
        at the same time, nonce tracking may be lost.

    .. note::

        Unlike HotWallet, this implementation does not expose private keys as they
        are securely stored in Cloud HSM. All signing operations are performed
        remotely in the HSM.
    """

    def __init__(self, config: Optional[BaseConfig] = None):
        """Initialize HSM wallet with optional Google Cloud KMS configuration.

        The wallet can be initialized either with explicit configuration via BaseConfig
        or using environment variables. If no config is provided, it will attempt to
        load configuration from environment variables.

        Args:
            config: Optional BaseConfig instance containing GCP project details and key information
                   If not provided, environment variables will be used
        """
        self.account = GCPKmsAccount(config=config)
        self.current_nonce: Optional[int] = None

    def __repr__(self):
        return f"<HSM wallet {self.account.address}>"

    @property
    def address(self) -> HexAddress:
        """Get the Ethereum address associated with the HSM key."""
        return self.account.address

    def get_main_address(self) -> HexAddress:
        """Get the main Ethereum address for this wallet."""
        return self.address

    def sync_nonce(self, web3: Web3) -> None:
        """Initialize the current nonce from on-chain data.

        Args:
            web3: Web3 instance connected to an Ethereum node
        """
        self.current_nonce = web3.eth.get_transaction_count(self.address)
        logger.info("Synced nonce for %s to %d", self.address, self.current_nonce)

    def allocate_nonce(self) -> int:
        """Get the next available nonce for transaction signing.

        Ethereum tx nonces are a counter. Each time this method is called,
        it returns the current nonce value and increments the counter.

        Returns:
            int: Next available nonce

        Raises:
            AssertionError: If nonce hasn't been synced yet
        """
        assert self.current_nonce is not None, "Nonce is not yet synced from the blockchain"
        nonce = self.current_nonce
        self.current_nonce += 1
        return nonce

    def sign_transaction_with_new_nonce(self, tx: dict) -> SignedTransactionWithNonce:
        """Sign a transaction using HSM and allocate a new nonce.

        Example:

        .. code-block:: python

            web3 = Web3(Web3.HTTPProvider('http://localhost:8545'))
            wallet = HSMWallet()  # Using env vars
            wallet.sync_nonce(web3)

            signed_tx = wallet.sign_transaction_with_new_nonce({
                "to": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "from": wallet.address,
                "value": web3.to_wei(0.1, "ether"),
                "gas": 21000,
                "gasPrice": web3.eth.gas_price,
                "chainId": web3.eth.chain_id,
                "data": "0x",
            })
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)

        Args:
            tx: Ethereum transaction data as a dict
               This is modified in-place to include nonce

        Returns:
            SignedTransactionWithNonce containing the signed transaction and metadata

        Raises:
            Exception: If transaction signing fails in the HSM
        """
        assert isinstance(tx, dict)
        assert "nonce" not in tx
        tx["nonce"] = self.allocate_nonce()

        signed_tx_bytes = self.account.sign_transaction(Web3HSMTransaction.from_dict(tx))
        if not signed_tx_bytes:
            raise Exception("Failed to sign transaction")

        signed = SignedTransactionWithNonce(
            rawTransaction=signed_tx_bytes,
            hash=Web3.keccak(signed_tx_bytes),
            v=signed_tx_bytes[-1],
            r=int.from_bytes(signed_tx_bytes[0:32], "big"),
            s=int.from_bytes(signed_tx_bytes[32:64], "big"),
            nonce=tx["nonce"],
            source=tx,
            address=self.address,
        )
        return signed

    def sign_bound_call_with_new_nonce(
        self,
        func: ContractFunction,
        tx_params: Optional[dict] = None,
    ) -> SignedTransactionWithNonce:
        """Sign a bound Web3 Contract call using HSM.

        Example:

        .. code-block:: python

            # Transfer 50 USDC
            transfer_call = usdc_contract.functions.transfer(
                recipient,
                50 * 10**6
            )
            signed_tx = wallet.sign_bound_call_with_new_nonce(transfer_call)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)

        With manual gas estimation:

        .. code-block:: python

            # Approve USDC spend
            approve_call = usdc_contract.functions.approve(
                spender_address,
                approve_amount
            )
            gas_estimation = estimate_gas_fees(web3)
            tx_params = apply_gas({"gas": 100_000}, gas_estimation)
            signed_tx = wallet.sign_bound_call_with_new_nonce(
                approve_call,
                tx_params
            )

        Args:
            func: Web3 contract function with bound arguments
            tx_params: Optional transaction parameters like gas settings

        Returns:
            SignedTransactionWithNonce containing the signed contract call
        """
        tx_params = tx_params or {}
        tx_params["from"] = self.address

        if "chainId" not in tx_params:
            tx_params["chainId"] = func.w3.eth.chain_id

        if tx_params:
            # Use given gas parameters
            tx = prepare_transaction(
                func.address,
                func.w3,
                fn_identifier=func.function_identifier,
                contract_abi=func.contract_abi,
                fn_abi=func.abi,
                transaction=tx_params,
                fn_args=func.args,
                fn_kwargs=func.kwargs,
            )
        else:
            # Use the default gas filler
            tx = func.build_transaction(tx_params)

        return self.sign_transaction_with_new_nonce(tx)

    def get_native_currency_balance(self, web3: Web3) -> Decimal:
        """Get the native currency balance (ETH, BNB, MATIC) of the wallet.

        Useful to check if you have enough cryptocurrency for gas fees.

        Args:
            web3: Web3 instance

        Returns:
            Current balance in ether units as Decimal
        """
        balance = web3.eth.get_balance(self.address)
        return web3.from_wei(balance, "ether")

    def transact_with_contract(
        self,
        func: ContractFunction,
        *args: Any,
        **kwargs: Any,
    ) -> SignedTransactionWithNonce:
        """Call a contract function using HSM signing.

        - Construct a tx payload ready for `web3.eth.send_raw_transaction`,
          signed using the HSM key

        - Remember to call :py:meth:`sync_nonce` before calling this method

        Example:

        .. code-block:: python

            # Approve USDC deposit to a vault contract
            deposit_amount = 500 * 10**6  # 500 USDC
            signed_tx = wallet.transact_with_contract(
                usdc.contract.functions.approve,
                Web3.to_checksum_address(vault.rebalance_address),
                deposit_amount
            )
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            assert_transaction_success_with_explanation(web3, tx_hash)

        Chain ID management:

        .. code-block:: python

            # Example with specific chain ID for cross-chain deployment
            signed_tx = wallet.transact_with_contract(
                contract.functions.initialize,
                owner_address,
                chainId=137  # Polygon mainnet
            )

        Args:
            func: Contract function to call
            *args: Arguments to pass to the contract function
            **kwargs: Additional arguments including transaction overrides

        Returns:
            Signed transaction ready for broadcasting

        Raises:
            ValueError: If contract function is not properly initialized
            Exception: If transaction signing fails
        """
        assert isinstance(func, ContractFunction), f"Got: {type(func)}"
        assert func.address is not None, f"ContractFunction is not bound to a contract instance: {func}"
        web3 = func.w3
        assert web3 is not None, "ContractFunction not bound to web3 instance"

        # Extract chainId and other tx overrides from kwargs
        tx_overrides = {}
        for key in ["chainId", "gas", "maxFeePerGas", "maxPriorityFeePerGas", "gasPrice"]:
            if key in kwargs:
                tx_overrides[key] = kwargs.pop(key)

        # Build transaction with function arguments
        tx_data = func(*args, **kwargs).build_transaction(
            {
                "from": self.address,
                **tx_overrides,
            }
        )

        # Fill in gas price if not provided
        if not any(key in tx_data for key in ["gasPrice", "maxFeePerGas"]):
            self.fill_in_gas_price(web3, tx_data)

        return self.sign_transaction_with_new_nonce(tx_data)

    @staticmethod
    def create_for_testing(web3: Web3, config: Optional[BaseConfig] = None, eth_amount: int = 99) -> "HSMWallet":
        """Creates a new HSM wallet for testing and seeds it with ETH.

        This is a test helper that:
        1. Creates a new HSM wallet
        2. Gets ETH from the first test account
        3. Initializes the nonce

        Example:

        .. code-block:: python

            # For local testing with environment variables
            web3 = Web3(Web3.HTTPProvider('http://localhost:8545'))
            wallet = HSMWallet.create_for_testing(web3)

            # For testing with specific config
            config = BaseConfig(...)
            wallet = HSMWallet.create_for_testing(web3, config)

            tx = {
                "to": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "value": 1,
                "gas": 100_000,
                "chainId": web3.eth.chain_id,
                "gasPrice": web3.eth.gas_price,
            }
            signed_tx = wallet.sign_transaction_with_new_nonce(tx)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)

        Args:
            web3: Web3 instance connected to a test node
            config: Optional HSM configuration (uses env vars if not provided)
            eth_amount: Amount of ETH to seed the wallet with (default: 99)

        Returns:
            Initialized and funded HSM wallet ready for testing
        """
        wallet = HSMWallet(config)
        tx_hash = web3.eth.send_transaction(
            {
                "from": web3.eth.accounts[0],  # Use first test account
                "to": wallet.address,
                "value": eth_amount * 10**18,
            }
        )
        web3.eth.wait_for_transaction_receipt(tx_hash)
        wallet.sync_nonce(web3)
        return wallet

    @staticmethod
    def fill_in_gas_price(web3: Web3, tx: dict) -> dict:
        """Fill in gas price fields for a transaction.

        - Estimates raw transaction gas usage
        - Uses web3 methods to get the gas value fields
        - Supports different backends (legacy, EIP-1559)
        - Queries values from the node

        .. note::

            Mutates ``tx`` in place.

        .. note::

            Before calling this method, you need to set ``gas`` and ``chainId``
            fields of ``tx``.

        Example:

        .. code-block:: python

            # Send small amount of ETH using HSM wallet
            tx_data = {
                "chainId": web3.eth.chain_id,
                "from": wallet.address,
                "to": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "value": Web3.to_wei(Decimal("0.1"), "ether"),
                "gas": 21000,
            }

            # Fill in optimal gas values
            wallet.fill_in_gas_price(web3, tx_data)
            signed_tx = wallet.sign_transaction_with_new_nonce(tx_data)

            # Broadcast the transaction
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)

        Args:
            web3: Web3 instance
            tx: Transaction dictionary to update with gas values

        Returns:
            Updated transaction dictionary with gas fields
        """
        price_data = estimate_gas_fees(web3)
        apply_gas(tx, price_data)
        return tx
