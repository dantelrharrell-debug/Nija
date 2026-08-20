from __future__ import annotations

import threading
import time

from bot import runtime_kraken_capital_tail_liveness_v173_patch as patch


class _FakeKraken:
    _FIAT_ASSETS = {"USD", "USDT", "USDC"}

    def __init__(self) -> None:
        self.account_identifier = "PLATFORM"
        self._price_cache = {}
        self._price_cache_lock = threading.Lock()
        self._last_pricing_coverage_pct = 0.0
        self.lookup_calls = 0

    def _normalize_kraken_asset_code(self, asset: str) -> str:
        token = str(asset).upper()
        return {"ZUSD": "USD", "XETH": "ETH"}.get(token, token)

    def _get_asset_usd_price(self, symbol: str):
        self.lookup_calls += 1
        return None


def test_kraken_default_stale_flight_rotation_waits_50_seconds() -> None:
    assert patch._kraken_rotation_threshold(25.0, 75.0, 90.0) == 50.0


def test_kraken_rotation_never_extends_broker_timeout_or_freshness() -> None:
    threshold = patch._kraken_rotation_threshold(25.0, 75.0, 90.0, 300.0)
    assert threshold == 70.0
    assert threshold < 75.0
    assert threshold < 90.0


def test_nonpositive_operator_override_cannot_rotate_before_existing_floor() -> None:
    threshold = patch._kraken_rotation_threshold(25.0, 75.0, 90.0, 2.0)
    assert threshold == 25.0


def test_recent_price_cache_is_used_without_live_lookup(monkeypatch) -> None:
    broker = _FakeKraken()
    broker._price_cache["ETH-USD"] = {"price": 2500.0, "ts": time.monotonic()}

    total = patch._compute_total_usd_balance_v173(
        broker,
        {"ZUSD": "100", "XETH": "0.1"},
        broker._get_asset_usd_price,
    )

    assert total == 350.0
    assert broker.lookup_calls == 0
    assert broker._last_pricing_coverage_pct == 1.0


def test_same_bound_price_resolver_is_not_called_twice_when_missing() -> None:
    broker = _FakeKraken()

    total = patch._compute_total_usd_balance_v173(
        broker,
        {"ZUSD": "100", "XETH": "0.1"},
        broker._get_asset_usd_price,
    )

    assert total == 100.0
    assert broker.lookup_calls == 1
    assert broker._last_pricing_coverage_pct == 0.0


def test_patch_exposes_no_freshness_or_execution_bypass_api() -> None:
    assert not hasattr(patch, "extend_freshness")
    assert not hasattr(patch, "accept_partial_snapshot")
    assert not hasattr(patch, "force_activation")
    assert not hasattr(patch, "grant_execution_authority")
