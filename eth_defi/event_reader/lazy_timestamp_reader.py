"""Lazily load block timestamps and headers."""
from hexbytes import HexBytes

from eth_defi.event_reader.conversion import convert_jsonrpc_value_to_int
from eth_typing import HexStr
from web3 import Web3
from web3.types import BlockIdentifier


class OutOfSpecifiedRangeRead(Exception):
    """We tried to read a block outside out original given range."""


class LazyTimestampContainer:
    """Dictionary-like object to get block timestamps on-demand.

    Lazily load any block timestamp over JSON-RPC API if we have not
    cached it yet.

    See :py:func:`extract_timestamps_json_rpc_lazy`.
    """

    def __init__(self, web3: Web3, start_block: int, end_block: int):
        """

        :param web3:
            Connection

        :param start_block:
            Start block range, inclusive

        :param end_block:
            End block range, inclusive
        """
        self.web3 = web3
        self.start_block = start_block
        self.end_block = end_block
        assert start_block > 0
        assert end_block >= start_block
        self.cache_by_block_hash = {}
        self.cache_by_block_number = {}

    def update_block_hash(self, block_identifier: BlockIdentifier) -> int:
        # Skip web3 stack of broken and slow result formatters
        if type(block_identifier) == int:
            assert block_identifier > 0
            result = self.web3.manager.request_blocking("eth_getBlockByNumber", (block_identifier, False))
        else:
            if isinstance(block_identifier, HexBytes):
                block_identifier = block_identifier.hex()
            result = self.web3.manager.request_blocking("eth_getBlockByHash", (block_identifier, False))

        # Note to self: block_number = 0 for the genesis block on Anvil
        block_number = convert_jsonrpc_value_to_int(result["number"])
        hash = result["hash"]

        # Make sure we conform the spec
        if not (self.start_block <= block_number <= self.end_block):
            raise OutOfSpecifiedRangeRead(f"Read block number {block_number:,} {hash} out of bounds of range {self.start_block:,} - {self.end_block:,}")

        timestamp = convert_jsonrpc_value_to_int(result["timestamp"])
        self.cache_by_block_hash[hash] = timestamp
        self.cache_by_block_number[block_number] = timestamp
        return timestamp

    def __getitem__(self, block_hash: HexStr | HexBytes | str):
        assert not type(block_hash) == int, f"Use block hashes, block numbers not supported, passed {block_hash}"

        assert type(block_hash) == str or isinstance(block_hash, HexBytes), f"Got: {block_hash} {block_hash.__class__}"

        if type(block_hash) != str:
            block_hash = block_hash.hex()

        if block_hash not in self.cache_by_block_hash:
            self.update_block_hash(block_hash)

        return self.cache_by_block_hash[block_hash]


def extract_timestamps_json_rpc_lazy(
    web3: Web3,
    start_block: int,
    end_block: int,
    fetch_boundaries=True,
) -> LazyTimestampContainer:
    """Create a cache container that instead of reading block timestamps upfront for the given range, only calls JSON-RPC API when requested

    - Works on the cases where sparse event data is read over long block range
      Use slow JSON-RPC block headers call to get this information.

    :return:
        Wrapper object for block hash based timestamp access.

    """
    container = LazyTimestampContainer(web3, start_block, end_block)
    if fetch_boundaries:
        container.update_block_hash(start_block)
        container.update_block_hash(end_block)
    return container
