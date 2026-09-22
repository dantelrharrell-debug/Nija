from __future__ import annotations

import inspect

from bot.broker_manager import KrakenBroker


def test_kraken_ws_market_aliases_are_canonicalized_for_strategy_universe():
    normalize = KrakenBroker._canonicalize_kraken_ws_market

    assert normalize("XBT/USD") == "BTC-USD"
    assert normalize("XBT/USDT") == "BTC-USDT"
    assert normalize("XDG/USD") == "DOGE-USD"
    assert normalize("ETH/USD") == "ETH-USD"
    assert normalize("BTC/USD") == "BTC-USD"


def test_kraken_product_discovery_uses_canonical_ws_market_normalizer():
    source = inspect.getsource(KrakenBroker.get_all_products)
    assert "self._canonicalize_kraken_ws_market(wsname)" in source
    assert "symbol = wsname.replace('/', '-')" not in source


def test_btc_alias_matches_heartbeat_canonical_candidate():
    from bot.trading_strategy import _HEARTBEAT_SYMBOL_CANDIDATES

    discovered = KrakenBroker._canonicalize_kraken_ws_market("XBT/USD")
    assert discovered == "BTC-USD"
    assert discovered == _HEARTBEAT_SYMBOL_CANDIDATES[0]
