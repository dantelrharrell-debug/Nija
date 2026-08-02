"""Tests for bot.kraken_symbol_resolver."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from bot.kraken_symbol_resolver import (
    KrakenSymbolResolver,
    ResolutionOutcome,
    ResolvedSymbol,
    _AssetPairsCache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api(ticker_prices=None, asset_pairs=None):
    """Build a minimal mock krakenex.API object.

    ticker_prices: dict mapping kraken_ticker → price string (last trade)
    asset_pairs:   dict mapping pair_key → info dict (for AssetPairs response)
    """
    api = MagicMock()

    def _query_public(endpoint, params=None):
        if endpoint == "AssetPairs":
            pairs = asset_pairs or {}
            return {"result": pairs}
        if endpoint == "Ticker":
            pair = (params or {}).get("pair", "")
            prices = ticker_prices or {}
            price_str = prices.get(pair)
            if price_str:
                return {"result": {pair: {"c": [str(price_str), "1"]}}}
            return {"result": {}}

    api.query_public.side_effect = _query_public
    return api


# ---------------------------------------------------------------------------
# _AssetPairsCache
# ---------------------------------------------------------------------------

class TestAssetPairsCache:
    def test_fresh_cache_is_stale(self):
        cache = _AssetPairsCache(ttl_seconds=3600)
        assert cache.is_stale() is True

    def test_refresh_populates_pairs(self):
        api = _make_api(asset_pairs={
            "XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"},
        })
        cache = _AssetPairsCache(ttl_seconds=3600)
        ok = cache.refresh(api)
        assert ok is True
        assert len(cache) == 1
        assert cache.is_stale() is False

    def test_find_ticker_by_wsname(self):
        api = _make_api(asset_pairs={
            "XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"},
        })
        cache = _AssetPairsCache(ttl_seconds=3600)
        cache.refresh(api)
        assert cache.find_ticker("XBT/USD") == "XXBTZUSD"

    def test_find_ticker_by_altname(self):
        api = _make_api(asset_pairs={
            "XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"},
        })
        cache = _AssetPairsCache(ttl_seconds=3600)
        cache.refresh(api)
        assert cache.find_ticker("XBTUSD") == "XXBTZUSD"

    def test_find_ticker_returns_none_for_unknown(self):
        cache = _AssetPairsCache(ttl_seconds=3600)
        assert cache.find_ticker("NONEXISTENTUSD") is None

    def test_refresh_returns_false_on_api_error(self):
        api = MagicMock()
        api.query_public.return_value = {"error": ["EAPI:Invalid nonce"]}
        cache = _AssetPairsCache(ttl_seconds=3600)
        ok = cache.refresh(api)
        assert ok is False


# ---------------------------------------------------------------------------
# KrakenSymbolResolver
# ---------------------------------------------------------------------------

class TestKrakenSymbolResolver:
    def _resolver_with(self, ticker_prices=None, asset_pairs=None) -> KrakenSymbolResolver:
        api = _make_api(ticker_prices=ticker_prices, asset_pairs=asset_pairs)
        return KrakenSymbolResolver(
            kraken_api=api,
            asset_pairs_ttl=9999,          # never stale during tests
            max_failures_before_unsupported=3,
        )

    def test_resolves_btc_directly(self):
        resolver = self._resolver_with(
            asset_pairs={"XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"}},
            ticker_prices={"XXBTZUSD": "50000"},
        )
        result = resolver.resolve("BTC-USD")
        assert result.price == pytest.approx(50000.0)
        assert result.outcome in (ResolutionOutcome.RESOLVED, ResolutionOutcome.ALIASED)

    def test_aliased_resolution_for_xbt(self):
        # Symbol passed as XBT-USD, pairs only have XXBTZUSD
        resolver = self._resolver_with(
            asset_pairs={"XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"}},
            ticker_prices={"XXBTZUSD": "50000"},
        )
        result = resolver.resolve("XBT-USD")
        assert result.price is not None

    def test_unsupported_after_max_failures(self):
        api = _make_api(ticker_prices={})  # no prices → every probe fails
        resolver = KrakenSymbolResolver(api, asset_pairs_ttl=9999, max_failures_before_unsupported=3)
        # First 2 calls return UNKNOWN
        for _ in range(2):
            r = resolver.resolve("AIR-USD")
            assert r.outcome == ResolutionOutcome.UNKNOWN
        # Third call triggers permanent-unavailable
        r = resolver.resolve("AIR-USD")
        assert r.outcome == ResolutionOutcome.UNSUPPORTED
        # Subsequent calls immediately return UNSUPPORTED (no API calls)
        call_count_before = api.query_public.call_count
        r = resolver.resolve("AIR-USD")
        assert r.outcome == ResolutionOutcome.UNSUPPORTED
        assert api.query_public.call_count == call_count_before  # no new calls

    def test_cached_resolution_avoids_extra_api_call(self):
        resolver = self._resolver_with(
            asset_pairs={"XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"}},
            ticker_prices={"XXBTZUSD": "50000"},
        )
        # First call populates cache
        r1 = resolver.resolve("BTC-USD")
        assert r1.price is not None
        call_count = resolver._api.query_public.call_count

        # Second call should use cache for ticker lookup
        r2 = resolver.resolve("BTC-USD")
        assert r2.outcome == ResolutionOutcome.CACHED
        assert r2.price == pytest.approx(50000.0)

    def test_is_unsupported_false_for_new_symbol(self):
        resolver = self._resolver_with()
        assert resolver.is_unsupported("NEWCOIN-USD") is False

    def test_get_price_returns_float_or_none(self):
        resolver = self._resolver_with(ticker_prices={"XXBTZUSD": "50000"},
                                       asset_pairs={"XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"}})
        price = resolver.get_price("BTC-USD")
        assert isinstance(price, float)

        # Unknown symbol → None
        assert resolver.get_price("DEFINITELYNOTREAL-USD") is None

    def test_cache_stats(self):
        resolver = self._resolver_with(
            asset_pairs={"XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"}},
            ticker_prices={"XXBTZUSD": "50000"},
        )
        resolver.resolve("BTC-USD")
        stats = resolver.get_cache_stats()
        assert stats["asset_pairs_count"] == 1
        assert stats["resolution_cache_size"] >= 1
        assert stats["unsupported_count"] == 0

    def test_refresh_asset_pairs(self):
        api = _make_api(asset_pairs={"XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD"}})
        resolver = KrakenSymbolResolver(api, asset_pairs_ttl=9999)
        ok = resolver.refresh_asset_pairs()
        assert ok is True
