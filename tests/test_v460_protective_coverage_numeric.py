"""v460: malformed numeric tracker evidence cannot certify protective exits.

Read-only, offline tests. Never connect to a broker, submit orders, or set
live execution readiness.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from bot import runtime_all_account_position_exit_coverage_v281_patch as v281


class Tracker:
    def __init__(self, positions):
        self.positions = dict(positions)

    def get_all_positions(self):
        return list(self.positions)

    def get_position(self, symbol):
        return self.positions[symbol]


class Broker:
    connected = True
    _startup_position_sync_fetch_ok = True
    _startup_position_sync_adopted = True
    _startup_position_sync_error = ""

    def __init__(self, row, *, dust=False):
        self._startup_position_sync_symbols = ("BTC-USD",)
        self._startup_position_sync_dust_symbols_v371 = (
            ("BTC-USD",) if dust else ()
        )
        self.position_tracker = Tracker({"BTC-USD": row})


def _manager(row, *, dust=False):
    return SimpleNamespace(
        _platform_brokers={"kraken": Broker(row, dust=dust)},
        _platform_failed_types=set(),
        _all_user_brokers={},
        user_brokers={},
        _user_metadata={},
        _failed_user_connections={},
        _users_without_credentials={},
    )


@pytest.fixture(autouse=True)
def no_broker_reads(monkeypatch):
    # These tests isolate tracker validation without broker I/O or v285 hooks.
    monkeypatch.setattr(
        v281, "_authoritative_snapshot_symbols",
        lambda broker: (True, set(broker._startup_position_sync_symbols), "test"),
    )


def _row(**overrides):
    result = {
        "quantity": 0.01,
        "entry_price": 50000.0,
        "cost_basis_verified": True,
        "auto_exit_blocked": False,
    }
    result.update(overrides)
    return result


@pytest.mark.parametrize("bad", [
    "nan", "inf", "-inf", "1e9999", "not-a-number", 10**1000,
    float("nan"), float("inf"), -float("inf"),
])
def test_invalid_quantity_cannot_disappear_from_protective_denominator(bad):
    result = v281.evaluate(_manager(_row(quantity=bad)), structural_exit_ready=True)
    assert result["ready"] is False
    reasons = result["pending"]["platform:kraken"]
    assert "tracker_quantity_invalid:BTC-USD" in reasons
    assert "authoritative_snapshot_missing_tracker_position:BTC-USD" in reasons
    assert result["positions"] == ()


def test_invalid_dust_quantity_is_still_unverified():
    result = v281.evaluate(
        _manager(_row(quantity="nan"), dust=True), structural_exit_ready=True,
    )
    assert result["ready"] is False
    assert "tracker_quantity_invalid:BTC-USD" in result["pending"]["platform:kraken"]


@pytest.mark.parametrize("bad", [
    "nan", "inf", "-inf", "1e9999", "broken", 10**1000,
    float("nan"), float("inf"), -float("inf"),
])
def test_invalid_entry_price_cannot_certify_an_actionable_position(bad):
    result = v281.evaluate(_manager(_row(entry_price=bad)), structural_exit_ready=True)
    assert result["ready"] is False
    assert "entry_price_unverified:BTC-USD" in result["pending"]["platform:kraken"]
    assert result["positions"][0]["protective_exit_verified"] is False
    assert result["positions"][0]["entry_price"] is None


def test_bad_entry_price_cannot_fallback_to_unverified_cost():
    row = _row(entry_price="nan", cost_basis_usd=1000)
    result = v281.evaluate(_manager(row), structural_exit_ready=True)
    assert result["ready"] is False
    assert "entry_price_unverified:BTC-USD" in result["pending"]["platform:kraken"]


def test_nonfinite_derived_entry_price_cannot_certify():
    row = _row()
    row.pop("entry_price")
    row["quantity"] = 1e-300
    row["cost_basis_usd"] = 1e300
    result = v281.evaluate(_manager(row), structural_exit_ready=True)
    assert result["ready"] is False
    assert "entry_price_unverified:BTC-USD" in result["pending"]["platform:kraken"]
    assert result["positions"][0]["entry_price"] is None


def test_valid_proven_position_behavior_is_unchanged():
    result = v281.evaluate(_manager(_row()), structural_exit_ready=True)
    assert result["ready"] is True
    assert result["pending"] == {}
    assert result["positions"][0]["entry_price"] == 50000.0
    assert result["positions"][0]["protective_exit_verified"] is True


def test_negative_real_quantity_is_not_zeroed_or_normalized():
    result = v281.evaluate(_manager(_row(quantity=-0.01)), structural_exit_ready=True)
    assert result["ready"] is True
    assert result["positions"][0]["quantity"] == -0.01


def test_exact_zero_quantity_retains_existing_nonholding_behavior():
    result = v281.evaluate(_manager(_row(quantity=0)), structural_exit_ready=True)
    assert result["ready"] is False  # Broker still reports BTC-USD holding.
    assert "authoritative_snapshot_missing_tracker_position:BTC-USD" in (
        result["pending"]["platform:kraken"]
    )


def test_float_parser_is_finite_only():
    assert v281._float("2.5") == 2.5
    for bad in ("nan", "inf", "-inf", "1e9999", 10**1000):
        assert math.isfinite(v281._float(bad))
        assert v281._float(bad) == 0.0
