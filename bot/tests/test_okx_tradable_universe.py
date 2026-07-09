"""Tests for OKX tradable universe filter (pre-scan broker universe cleanup).

Requirement: NIJA must not reach AI scoring or Phase-3 candidate selection for
OKX symbols that are invalid, synthetic, or not listed on the live OKX instruments
endpoint.  Valid liquid broker-listed symbols must pass the full funnel.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_okx_patch_state():
    """Reset module-level caches so tests don't pollute each other."""
    import bot.okx_runtime_patch as p  # noqa: PLC0415
    p._UNIVERSE_QUARANTINE.clear()
    p._INVALID_OKX_INST_IDS.clear()
    p._VOLUME_FAIL_COUNTS.clear()
    p._PRODUCT_CACHE.update({"loaded_at": 0.0, "symbols": set()})


def _make_okx_broker(products: "set[str] | None" = None) -> Any:
    """Return a minimal OKX-like broker stub."""

    class _FakeRestClient:
        def __init__(self, products):
            self._products = products or set()

        def _request(self, method, path, *, params=None, **kw):
            if path == "/api/v5/public/instruments" and "instType" in (params or {}):
                return {
                    "code": "0",
                    "data": [{"instId": s} for s in self._products],
                }
            return {"code": "0", "data": []}

    class _OKXBroker:
        pass

    broker = _OKXBroker()
    rest = _FakeRestClient(products or set())
    broker.market_api = rest
    broker.account_api = rest
    return broker


# ---------------------------------------------------------------------------
# 1. Universe filter: synthetic cash pairs are quarantined
# ---------------------------------------------------------------------------

def test_synthetic_cash_pairs_quarantined():
    """Synthetic cash pairs (USD-USDT, etc.) must be removed from the scan universe."""
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()

    broker = _make_okx_broker({"BTC-USDT", "ETH-USDT", "SOL-USDT"})
    symbols = ["BTC-USDT", "ETH-USDT", "USD-USDT", "USDT-USD", "USD-USDC", "SOL-USDT"]

    # Pre-warm product cache so the live HTTP call is not needed
    p._PRODUCT_CACHE["loaded_at"] = time.time()
    p._PRODUCT_CACHE["symbols"] = {"BTC-USDT", "ETH-USDT", "SOL-USDT"}

    filtered, stats = p.filter_symbols_for_broker(broker, symbols)

    assert "BTC-USDT" in filtered
    assert "ETH-USDT" in filtered
    assert "SOL-USDT" in filtered
    assert "USD-USDT" not in filtered
    assert "USDT-USD" not in filtered
    assert "USD-USDC" not in filtered

    assert stats["tradeable"] == 3
    assert stats["quarantine_reason_synthetic"] >= 2
    assert stats["total"] == 6


# ---------------------------------------------------------------------------
# 2. Universe filter: not-listed symbols are quarantined
# ---------------------------------------------------------------------------

def test_not_listed_symbols_quarantined():
    """Symbols absent from the OKX live instruments list must be quarantined."""
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()

    broker = _make_okx_broker({"BTC-USDT", "ETH-USDT"})
    symbols = ["BTC-USDT", "ETH-USDT", "FAKE-USDT", "GHOST-USDT"]

    p._PRODUCT_CACHE["loaded_at"] = time.time()
    p._PRODUCT_CACHE["symbols"] = {"BTC-USDT", "ETH-USDT"}

    filtered, stats = p.filter_symbols_for_broker(broker, symbols)

    assert "BTC-USDT" in filtered
    assert "ETH-USDT" in filtered
    assert "FAKE-USDT" not in filtered
    assert "GHOST-USDT" not in filtered

    assert stats["tradeable"] == 2
    assert stats["quarantine_reason_not_listed"] == 2
    assert "FAKE-USDT" in p._UNIVERSE_QUARANTINE
    assert "GHOST-USDT" in p._UNIVERSE_QUARANTINE


# ---------------------------------------------------------------------------
# 3. Universe filter: volume-fail quarantine gates repeated dead symbols
# ---------------------------------------------------------------------------

def test_repeated_volume_fail_quarantines_symbol():
    """A symbol that hits VOLUME_TOO_LOW repeatedly is moved to the quarantine."""
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()

    # Simulate threshold-many failures
    threshold = p._VOLUME_FAIL_QUARANTINE_THRESHOLD
    for _ in range(threshold):
        p.record_okx_volume_fail("DEAD-USDT")

    assert "DEAD-USDT" in p._UNIVERSE_QUARANTINE

    broker = _make_okx_broker({"DEAD-USDT", "BTC-USDT"})
    p._PRODUCT_CACHE["loaded_at"] = time.time()
    p._PRODUCT_CACHE["symbols"] = {"DEAD-USDT", "BTC-USDT"}

    filtered, stats = p.filter_symbols_for_broker(broker, ["DEAD-USDT", "BTC-USDT"])

    assert "BTC-USDT" in filtered
    assert "DEAD-USDT" not in filtered
    assert stats["quarantine_reason_volume_fail"] == 1


# ---------------------------------------------------------------------------
# 4. Universe filter: non-OKX broker returns list unchanged
# ---------------------------------------------------------------------------

def test_non_okx_broker_symbols_unchanged():
    """For Coinbase / Kraken / Alpaca brokers the filter must be a no-op."""
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()

    class _CoinbaseBroker:
        pass

    broker = _CoinbaseBroker()
    symbols = ["BTC-USD", "ETH-USD", "USD-USDT"]

    filtered, stats = p.filter_symbols_for_broker(broker, symbols)

    assert filtered == symbols
    assert stats["tradeable"] == len(symbols)
    assert stats["quarantined"] == 0


# ---------------------------------------------------------------------------
# 5. Empty product cache — filter does not block any symbols
# ---------------------------------------------------------------------------

def test_empty_product_cache_allows_all():
    """If the OKX product cache is empty (REST unavailable), no symbols are removed."""
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()
    # Ensure cache is empty
    p._PRODUCT_CACHE.update({"loaded_at": 0.0, "symbols": set()})

    class _OKXBroker:
        pass

    broker = _OKXBroker()
    # No market_api → _load_okx_products_from_rest returns empty set
    symbols = ["BTC-USDT", "ETH-USDT", "UNKNOWN-USDT"]

    filtered, stats = p.filter_symbols_for_broker(broker, symbols)

    # All non-synthetic symbols pass when the product list cannot be loaded
    assert "BTC-USDT" in filtered
    assert "ETH-USDT" in filtered
    assert "UNKNOWN-USDT" in filtered
    assert stats["quarantine_reason_not_listed"] == 0


# ---------------------------------------------------------------------------
# 6. Integration: valid liquid symbol passes filter and is tradeable
# ---------------------------------------------------------------------------

def test_valid_liquid_okx_symbol_passes_filter():
    """A valid OKX-listed symbol with real volume passes the pre-scan filter."""
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()

    valid_symbols = {"BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT"}
    broker = _make_okx_broker(valid_symbols)
    p._PRODUCT_CACHE["loaded_at"] = time.time()
    p._PRODUCT_CACHE["symbols"] = set(valid_symbols)

    input_symbols = list(valid_symbols) + ["USD-USDT", "FAKE-USDT", "GHOST-USDT"]
    filtered, stats = p.filter_symbols_for_broker(broker, input_symbols)

    # All 4 valid symbols must survive
    for sym in valid_symbols:
        assert sym in filtered, f"{sym} should survive the tradable universe filter"

    # Invalid/not-listed symbols must be blocked
    assert "USD-USDT" not in filtered
    assert "FAKE-USDT" not in filtered
    assert "GHOST-USDT" not in filtered

    assert stats["tradeable"] == len(valid_symbols)
    assert stats["quarantined"] >= 3  # at least the 3 invalid ones


# ---------------------------------------------------------------------------
# 7. Symbol normalization — Coinbase/Kraken-style symbols become OKX instIds
# ---------------------------------------------------------------------------

def test_symbol_normalization_converts_to_okx_format():
    """Coinbase-style BTC-USD is normalized to BTC-USDT for OKX listing check."""
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()

    class _OKXBroker:
        pass

    broker = _OKXBroker()
    broker.market_api = None

    # Product cache has BTC-USDT; caller provides BTC-USD (Coinbase format)
    p._PRODUCT_CACHE["loaded_at"] = time.time()
    p._PRODUCT_CACHE["symbols"] = {"BTC-USDT"}

    filtered, stats = p.filter_symbols_for_broker(broker, ["BTC-USD"])

    # BTC-USD normalizes to BTC-USDT which IS in products → must survive
    assert len(filtered) == 1
    assert stats["tradeable"] == 1
    assert stats["quarantine_reason_not_listed"] == 0


# ---------------------------------------------------------------------------
# 8. TRADABLE_UNIVERSE_BUILT log emitted by run_scan_phase
# ---------------------------------------------------------------------------

def test_tradable_universe_built_log_emitted_by_run_scan_phase(caplog):
    """run_scan_phase must emit TRADABLE_UNIVERSE_BUILT log for the pre-scan filter."""
    import logging
    import bot.okx_runtime_patch as p

    _reset_okx_patch_state()

    # Patch filter_symbols_for_broker to track calls without a real broker
    calls: list = []
    original_filter = p.filter_symbols_for_broker

    def _spy_filter(broker, symbols):
        result = original_filter(broker, symbols)
        calls.append(result)
        return result

    # Minimal NijaCoreLoop shim — only test that the log line appears
    try:
        from bot.nija_core_loop import NijaCoreLoop  # type: ignore
    except Exception:
        import pytest
        pytest.skip("NijaCoreLoop import failed in this environment")

    # Patch filter import inside nija_core_loop during the call
    import sys
    import importlib

    _okx_mod = sys.modules.get("bot.okx_runtime_patch")
    if _okx_mod is None:
        import pytest
        pytest.skip("okx_runtime_patch not loaded")

    original = _okx_mod.filter_symbols_for_broker
    _okx_mod.filter_symbols_for_broker = _spy_filter

    try:
        with caplog.at_level(logging.INFO, logger="nija.core_loop"):
            # Build a minimal apex stub that satisfies NijaCoreLoop.__init__
            apex_stub = SimpleNamespace(
                broker_client=None,
                broker_manager=None,
                risk_manager=None,
                state_machine=None,
                _get_broker_name=lambda: "okx",
                calculate_indicators=lambda df: {},
                check_market_filter=lambda df, ind: (False, "neutral", "no_signal"),
                analyze_market=lambda *a, **kw: {"action": "hold"},
                volume_min_threshold=0.0,
            )
            try:
                loop = NijaCoreLoop(apex_stub)
            except Exception:
                import pytest
                pytest.skip("NijaCoreLoop construction failed in test environment")

            class _FakeOKXBroker:
                connected = True
                broker_type = SimpleNamespace(value="okx")

            broker = _FakeOKXBroker()
            p._PRODUCT_CACHE["loaded_at"] = time.time()
            p._PRODUCT_CACHE["symbols"] = {"BTC-USDT"}

            # Calling run_scan_phase with a tiny symbol list; it will bail
            # quickly — we only need the TRADABLE_UNIVERSE_BUILT log.
            loop.run_scan_phase(broker=broker, balance=500.0, symbols=["BTC-USDT", "USD-USDT"])

        logged_messages = [r.message for r in caplog.records]
        assert any("TRADABLE_UNIVERSE_BUILT" in m for m in logged_messages), (
            "TRADABLE_UNIVERSE_BUILT must appear in log output. "
            f"Logged: {logged_messages[:20]}"
        )
    finally:
        _okx_mod.filter_symbols_for_broker = original
