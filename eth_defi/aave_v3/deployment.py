"""Aave v3 deployments."""
from dataclasses import dataclass
from typing import NamedTuple

from eth_typing import HexAddress
from web3 import Web3
from web3.contract import Contract


class AaveV3ReserveConfiguration(NamedTuple):
    # https://github.com/aave/aave-v3-core/blob/e0bfed13240adeb7f05cb6cbe5e7ce78657f0621/contracts/misc/AaveProtocolDataProvider.sol#L77

    #: Asset decimals
    decimals: int

    #: Loan to Value of the reserve
    ltv: int

    #: Liquidation threshold of the reserve
    liquidation_threshold: int

    #: Liquidation bonus of the reserve
    liquidation_bonus: int

    #: Reserve factor
    reserve_factor: int

    #: Asset can be used as collateral
    usage_as_collateral_enabled: bool

    #: Borrowing is enabled
    borrowing_enabled: bool

    #: Stable rate borrowing enabled
    stable_borrow_rate_enabled: bool

    #: Reserve is active
    is_active: bool

    #: Reserve is frozen
    is_frozen: bool


class AaveV3UserData(NamedTuple):
    # https://github.com/aave/aave-v3-core/blob/62dfda56bd884db2c291560c03abae9727a7635e/contracts/interfaces/IPool.sol#L483

    #: The total collateral of the user in the base currency used by the price feed
    total_collateral_base: int

    #: The total debt of the user in the base currency used by the price feed
    total_debt_base: int

    #: The borrowing power left of the user in the base currency used by the price feed
    available_borrows_base: int

    #: The liquidation threshold of the user
    current_liquidation_threshold: int

    #: The loan to value of the user
    ltv: int

    #: The current health factor of the user
    health_factor: int


@dataclass(frozen=True)
class AaveV3Deployment:
    """Describe Aave v3 deployment."""

    #: The Web3 instance for which all the contracts here are bound
    web3: Web3

    #: Aave v3 pool contract proxy
    pool: Contract

    #: AaveProtocolDataProvider contract
    data_provider: Contract

    #: AaveOracle contract
    oracle: Contract

    def get_reserve_configuration_data(self, token_address: HexAddress) -> AaveV3ReserveConfiguration:
        """Returns reserve configuration data."""
        # https://github.com/aave/aave-v3-core/blob/e0bfed13240adeb7f05cb6cbe5e7ce78657f0621/contracts/misc/AaveProtocolDataProvider.sol#L77
        data = self.data_provider.functions.getReserveConfigurationData(token_address).call()
        return AaveV3ReserveConfiguration(*data)

    def get_price(self, token_address: HexAddress) -> int:
        """Returns asset latest price using Aave oracle."""
        # https://github.com/aave/aave-v3-core/blob/e0bfed13240adeb7f05cb6cbe5e7ce78657f0621/contracts/misc/AaveOracle.sol#L104
        return self.oracle.functions.getAssetPrice(token_address).call()

    def get_user_data(self, user_address: HexAddress) -> AaveV3UserData:
        """Returns the user account data across all the reserves."""
        # https://github.com/aave/aave-v3-core/blob/62dfda56bd884db2c291560c03abae9727a7635e/contracts/interfaces/IPool.sol#L490
        data = self.pool.functions.getUserAccountData(user_address).call()
        return AaveV3UserData(*data)
