"""Analyse Lagoon protocol deposits and redemptions.

- To track our treasury balance

- Find Lagoon events here https://github.com/hopperlabsxyz/lagoon-v0/blob/b790b1c1fbb51a101b0c78a4bb20e8700abed054/src/vault/primitives/Events.sol
"""
import datetime
from dataclasses import dataclass
from decimal import Decimal

from hexbytes import HexBytes
from web3._utils.events import EventLogErrorFlags

from eth_defi.lagoon.vault import LagoonVault
from eth_defi.timestamp import get_block_timestamp
from eth_defi.token import TokenDetails


@dataclass(slots=True, frozen=True)
class LagoonSettlementEvent:
    """Capture Lagoon vault flow when it is settled.

    - Use to adjust vault treasury balances for internal accounting
    - We do not capture individual users
    """

    #: Chain we checked
    chain_id: int

    #: settleDeposit() transaction by the asset managre
    tx_hash: HexBytes

    #: When the settlement was done
    block_number: int

    #: When the settlement was done
    timestamp: datetime.datetime

    #: Vault address
    vault: LagoonVault

    #: How much new underlying was added to the vault
    deposited: Decimal

    #: How much was redeemed successfully
    redeemed: Decimal

    #: Shares added for new investor
    shares_minted: Decimal

    #: Shares burned for redemptions
    shares_burned: Decimal

    @property
    def underlying(self) -> TokenDetails:
        """Get USDC."""
        return self.vault.underlying_token

    @property
    def share_token(self) -> TokenDetails:
        """Get USDC."""
        return self.vault.share_token

    def get_serialiable_diagnostics_data(self) -> dict:
        """JSON serialisable diagnostics data for logging"""
        return {
            "chain_id": self.chain_id,
            "block_number": self.block_number,
            "timestamp": self.timestamp,
            "tx_hash": self.tx_hash.hex(),
            "vault": self.vault.vault_address,
            "underlying": self.underlying.address,
            "share_token": self.share_token.address,
            "deposited": self.deposited,
            "redeemed": self.redeemed,
            "shares_minted": self.shares_minted,
            "shares_burned": self.shares_minted,
        }

def analyse_vault_flow_in_settlement(
    vault: LagoonVault,
    tx_hash: HexBytes,
) -> LagoonSettlementEvent:
    """Extract deposit and redeem events from a settlement transaction"""
    web3 = vault.web3
    receipt = web3.eth.get_transaction_receipt(tx_hash)
    assert receipt is not None, f"Cannot find tx: {tx_hash}"
    assert isinstance(tx_hash, HexBytes), f"Got {tx_hash}"

    deposits = vault.vault_contract.events.SettleDeposit().process_receipt(receipt, errors=EventLogErrorFlags.Discard)
    redeems = vault.vault_contract.events.SettleRedeem().process_receipt(receipt, errors=EventLogErrorFlags.Discard)

    assert len(deposits) == 1, f"Does not look like settleDeposit() tx: {tx_hash.hex()}"

    new_deposited_raw = sum(log["args"]["assetsDeposited"] for log in deposits)
    new_minted_raw = sum(log["args"]["sharesMinted"] for log in deposits)

    new_redeem_raw = sum(log["args"]["assetsWithdrawed"] for log in redeems)
    new_burned_raw = sum(log["args"]["sharesBurned"] for log in redeems)

    block_number = receipt["blockNumber"]
    timestamp = get_block_timestamp(web3, block_number)

    return LagoonSettlementEvent(
        chain_id=vault.chain_id,
        tx_hash=tx_hash,
        block_number=block_number,
        timestamp=timestamp,
        vault=vault,
        deposited=vault.underlying_token.convert_to_decimals(new_deposited_raw),
        redeemed=vault.underlying_token.convert_to_decimals(new_redeem_raw),
        shares_minted=vault.share_token.convert_to_decimals(new_minted_raw),
        shares_burned=vault.share_token.convert_to_decimals(new_burned_raw),
    )
