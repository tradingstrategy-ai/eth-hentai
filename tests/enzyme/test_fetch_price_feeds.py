"""Fetch enzyme price feeds.

"""
from functools import partial
from typing import cast
from decimal import Decimal

import pytest
from eth.constants import ZERO_ADDRESS
from eth_typing import HexAddress
from web3 import Web3, HTTPProvider
from web3.contract import Contract
from web3.exceptions import ContractLogicError

from eth_defi.deploy import deploy_contract
from eth_defi.enzyme.deployment import EnzymeDeployment, RateAsset
from eth_defi.enzyme.events import fetch_vault_balance_events, Deposit, Redemption
from eth_defi.enzyme.price_feed import fetch_price_feeds, EnzymePriceFeed
from eth_defi.enzyme.uniswap_v2 import prepare_swap
from eth_defi.enzyme.vault import Vault
from eth_defi.event_reader.multithread import MultithreadEventReader
from eth_defi.event_reader.reader import extract_events, Web3EventReader
from eth_defi.token import fetch_erc20_details
from eth_defi.trace import assert_transaction_success_with_explanation, TransactionAssertionError, assert_call_success_with_explanation
from eth_defi.uniswap_v2.deployment import UniswapV2Deployment


@pytest.fixture
def deployment(
    web3: Web3,
    deployer: HexAddress,
    user_1: HexAddress,
    weth: Contract,
    mln: Contract,
    usdc: Contract,
    weth_usd_mock_chainlink_aggregator: Contract,
    usdc_usd_mock_chainlink_aggregator: Contract,
) -> EnzymeDeployment:
    """Create Enzyme deployment that supports WETH and USDC tokens"""

    deployment = EnzymeDeployment.deploy_core(
        web3,
        deployer,
        mln,
        weth,
    )

    deployment.add_primitive(
        usdc,
        usdc_usd_mock_chainlink_aggregator,
        RateAsset.USD,
    )

    deployment.add_primitive(
        weth,
        weth_usd_mock_chainlink_aggregator,
        RateAsset.USD,
    )
    return deployment


def test_fetch_price_feeds(
    web3: Web3,
    deployment: EnzymeDeployment,
):
    """Fetch all deployed Enzyme price feeds."""

    provider = cast(HTTPProvider, web3.provider)
    json_rpc_url = provider.endpoint_uri
    reader = MultithreadEventReader(json_rpc_url, max_threads=16)

    start_block = 1
    end_block = web3.eth.block_number

    feed_iter = fetch_price_feeds(
        deployment,
        start_block,
        end_block,
        reader,
    )
    feeds = list(feed_iter)
    reader.close()
    assert len(feeds) == 2
    assert feeds[0].primitive_token.symbol == "USDC"
    assert feeds[1].primitive_token.symbol == "WETH"


def test_unsupported_base_asset(
    web3: Web3,
    deployment: EnzymeDeployment,
    weth: Contract,
    usdc: Contract,
    weth_usd_mock_chainlink_aggregator: Contract):
    """See what ValueInterpreter replies if it does not know about the asset"""

    # Check the underlying price feed is correctly configured
    # and print a Solidity stack trace of errors if any
    value_interpreter = deployment.contracts.value_interpreter
    raw_amount = 10**18
    with pytest.raises(ContractLogicError) as e:
        result = value_interpreter.functions.calcCanonicalAssetValue(
            ZERO_ADDRESS,
            raw_amount,
            usdc.address,
        ).call()
    assert e.value.args[0] == 'execution reverted: __calcAssetValue: Unsupported _baseAsset'


def test_manipulate_price(
    web3: Web3,
    deployment: EnzymeDeployment,
    weth: Contract,
    usdc: Contract,
    weth_usd_mock_chainlink_aggregator: Contract,
):
    """Set the underlying price for Enzyme price feed."""

    weth_token = fetch_erc20_details(web3, weth.address)
    usdc_token = fetch_erc20_details(web3, usdc.address)
    feed = EnzymePriceFeed.fetch_price_feed(deployment, weth_token)

    # Check that our mocker is good
    mock_data = weth_usd_mock_chainlink_aggregator.functions.latestRoundData().call()
    assert len(mock_data) == 5

    call = weth_usd_mock_chainlink_aggregator.functions.latestRoundData()
    mock_data = assert_call_success_with_explanation(call)
    assert len(mock_data) == 5

    # Check the underlying price feed is correctly configured
    # and print a Solidity stack trace of errors if any
    value_interpreter = deployment.contracts.value_interpreter
    raw_amount = weth_token.convert_to_raw(Decimal(1))
    call = value_interpreter.functions.calcCanonicalAssetValue(
        weth_token.address,
        raw_amount,
        usdc_token.address,
    )
    result = assert_call_success_with_explanation(call)

    price = feed.calculate_current_onchain_price(usdc_token)
    assert price == 1600
