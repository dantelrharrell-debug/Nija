"""Prevent transient Kraken public AssetPairs misses from blocking spot dust valuation.

All broker/public calls are fake; no order, position mutation or synthetic price.
"""
from __future__ import annotations

from bot import kraken_equity_runtime_patch as equity


def test_negative_asset_pair_cache_expires_without_guessing_price(monkeypatch):
    now = [100.0]
    attempts = []
    replies = [False]

    class Broker:
        pass

    broker = Broker()
    monkeypatch.setattr(equity.time, "monotonic", lambda: now[0])

    def api(_broker, method, params=None):
        attempts.append((method, (params or {}).get("pair")))
        if not replies[0]:
            return {"error": ["temporary"], "result": {}}
        return {"error": [], "result": {"BABYUSD": {
            "altname": "BABYUSD", "quote": "ZUSD", "wsname": "BABY/USD",
        }}}

    monkeypatch.setattr(equity, "_public_call", api)
    equity._PAIR_CACHE.clear()
    try:
        assert equity._resolve_asset_pair(broker, "BABY") is None
        before = len(attempts)
        now[0] = 120.0
        replies[0] = True
        assert equity._resolve_asset_pair(broker, "BABY") is None
        assert len(attempts) == before
        now[0] = 131.0
        assert equity._resolve_asset_pair(broker, "BABY") == ("BABYUSD", "USD")
        assert len(attempts) > before
    finally:
        equity._PAIR_CACHE.clear()


def test_positive_asset_pair_cache_retains_long_ttl(monkeypatch):
    now = [100.0]
    calls = [0]

    class Broker:
        pass

    broker = Broker()
    monkeypatch.setattr(equity.time, "monotonic", lambda: now[0])

    def api(_broker, method, params=None):
        calls[0] += 1
        return {"error": [], "result": {"ETHUSD": {
            "altname": "ETHUSD", "quote": "ZUSD", "wsname": "ETH/USD",
        }}}

    monkeypatch.setattr(equity, "_public_call", api)
    equity._PAIR_CACHE.clear()
    try:
        assert equity._resolve_asset_pair(broker, "ETH") == ("ETHUSD", "USD")
        first = calls[0]
        now[0] = 1700.0
        assert equity._resolve_asset_pair(broker, "ETH") == ("ETHUSD", "USD")
        assert calls[0] == first
        now[0] = 1901.0
        assert equity._resolve_asset_pair(broker, "ETH") == ("ETHUSD", "USD")
        assert calls[0] > first
    finally:
        equity._PAIR_CACHE.clear()


def test_unresolved_asset_never_creates_a_market_price(monkeypatch):
    class Broker:
        pass

    broker = Broker()
    monkeypatch.setattr(equity, "_public_call", lambda *_a, **_kw: {"error": ["offline"], "result": {}})
    equity._PAIR_CACHE.clear()
    equity._PRICE_CACHE.clear()
    try:
        positions = equity._build_positions(broker, {"BABY": 0.00856})
        assert len(positions) == 1
        assert positions[0]["quantity"] == 0.00856
        assert positions[0]["current_price"] == 0.0
        assert positions[0]["size_usd"] == 0.0
        assert positions[0]["price_source"] == "unavailable"
    finally:
        equity._PAIR_CACHE.clear()
        equity._PRICE_CACHE.clear()
