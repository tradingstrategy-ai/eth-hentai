from decimal import Decimal
from dataclasses import dataclass
from typing import List, Optional

from eth_typing import HexAddress


@dataclass
class TradeResult:
    """A base class for Success/Fail trade result."""

    #: How many units of gas we burned
    gas_used: int

    #: What as the gas price used in wei.
    #: Set to `0` if not available.
    effective_gas_price: int

    def get_effective_gas_price_gwei(self) -> Decimal:
        return Decimal(self.effective_gas_price) / Decimal(10**9)


@dataclass
class TradeSuccess(TradeResult):
    """Describe the result of a successful Uniswap swap.

    See :py:func:`eth_defi.uniswap_v2.analysis.analyse_trade_by_receipt`
    """

    #: Routing path that was used for this trade
    path: Optional[List[HexAddress]]

    amount_in: int
    amount_out_min: Optional[int]
    amount_out: int

    #: Overall price paid as in token (first in the path) to out token (last in the path).
    #:
    #: Price includes any fees paid during the order routing path.
    #:
    #: Note that you get inverse price, if you route ETH-USD or USD-ETH e.g. are you doing buy or sell.
    #:
    #: See also :py:meth:`get_human_price)`
    price: Decimal

    #: Token information book keeping
    amount_in_decimals: int

    #: Token information book keeping
    amount_out_decimals: int

    def get_human_price(self, reverse_token_order=False) -> Decimal:
        """Get the executed price of this trade.

        :param reverse_token_order:
            Base and quote token order.

            Quote token should be natural quote token  like USD or ETH based token of the trade.
            If `reverse_token_order` is set quote token is `token0` of the pool,
            otherwise `token1`.
        """
        if reverse_token_order:
            return self.price / Decimal(1)
        else:
            return self.price


@dataclass
class TradeFail(TradeResult):
    """Describe the result of a failed Uniswap swap.

    The transaction reverted for a reason or another.
    """

    #: Revert reason if we managed to extract one
    revert_reason: Optional[str] = None
