from __future__ import annotations

import os

import pytest

from bot.exchange_kill_switch import ExchangeKillSwitchConfig, ExchangeKillSwitchProtector, GateStatus
from bot import exchange_rejection_sample_guard_v222_patch as v222


@pytest.fixture(autouse=True)
def _min_samples(monkeypatch):
    monkeypatch.setenv("NIJA_ORDER_REJECT_MIN_SAMPLES", "5")
    assert v222._patch_rejection_gate()


def _protector(tmp_path):
    cfg = ExchangeKillSwitchConfig(
        order_window_size=20,
        order_reject_rate_threshold=0.5,
        order_reject_rate_caution=0.25,
        auto_trigger_enabled=False,
    )
    protector = ExchangeKillSwitchProtector(cfg)
    protector.STATE_FILE = tmp_path / "exchange_kill_switch_state.json"
    protector.reset("v222 test isolation")
    return protector


def test_single_rejection_is_insufficient_for_red(tmp_path):
    protector = _protector(tmp_path)
    protector.record_order_result("first-rejection", accepted=False)

    gate = protector._gate_order_rejection()

    assert gate.status == GateStatus.YELLOW
    assert gate.detail["window_orders"] == 1
    assert gate.detail["rejected"] == 1
    assert gate.detail["sample_sufficient"] is False
    assert gate.detail["minimum_samples_for_red"] == 5


def test_high_rate_below_minimum_sample_stays_yellow(tmp_path):
    protector = _protector(tmp_path)
    protector.record_order_result("bad-1", accepted=False)
    protector.record_order_result("bad-2", accepted=False)
    protector.record_order_result("ok-1", accepted=True)
    protector.record_order_result("ok-2", accepted=True)

    gate = protector._gate_order_rejection()

    assert gate.status == GateStatus.YELLOW
    assert gate.detail["rejection_rate_pct"] == 50.0
    assert gate.detail["sample_sufficient"] is False


def test_red_gate_still_works_once_minimum_sample_is_met(tmp_path):
    protector = _protector(tmp_path)
    for order_id in ("bad-1", "bad-2", "bad-3"):
        protector.record_order_result(order_id, accepted=False)
    for order_id in ("ok-1", "ok-2"):
        protector.record_order_result(order_id, accepted=True)

    gate = protector._gate_order_rejection()

    assert gate.status == GateStatus.RED
    assert gate.detail["window_orders"] == 5
    assert gate.detail["rejected"] == 3
    assert gate.detail["sample_sufficient"] is True


def test_exact_legacy_single_sample_exchange_stop_is_eligible():
    ok, detail = v222._exact_single_sample_stop(
        {
            "source": "EXCHANGE_MONITOR",
            "reason": "Exchange kill-switch: Order rejection rate 100.0% >= 50% (1/1 orders rejected)",
        }
    )

    assert ok is True
    assert "1/1 orders rejected" in detail


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("UI", "Exchange kill-switch: Order rejection rate 100.0% >= 50% (1/1 orders rejected)"),
        ("FAILURE_MODE_MANAGER", "Exchange kill-switch: Order rejection rate 100.0% >= 50% (1/1 orders rejected)"),
        ("EXCHANGE_MONITOR", "Exchange kill-switch: Order rejection rate 100.0% >= 50% (2/2 orders rejected)"),
        ("EXCHANGE_MONITOR", "Exchange kill-switch: Order rejection rate 50.0% >= 50% (5/10 orders rejected)"),
        ("EXCHANGE_MONITOR", "Exchange kill-switch: Order rejection rate 100.0% >= 50% (1/1 orders rejected) manual"),
    ],
)
def test_recovery_signature_rejects_non_exact_or_unsafe_stops(source, reason):
    ok, _ = v222._exact_single_sample_stop({"source": source, "reason": reason})
    assert ok is False


def test_minimum_samples_is_bounded(monkeypatch):
    cfg = ExchangeKillSwitchConfig(order_window_size=4)

    monkeypatch.setenv("NIJA_ORDER_REJECT_MIN_SAMPLES", "1")
    assert v222._minimum_samples(cfg) == 2

    monkeypatch.setenv("NIJA_ORDER_REJECT_MIN_SAMPLES", "99")
    assert v222._minimum_samples(cfg) == 4


def test_insufficient_sample_gate_still_exposes_rejection_reasons(tmp_path):
    protector = _protector(tmp_path)
    protector.record_order_result("bad-1", accepted=False)

    gate = protector._gate_order_rejection()

    assert gate.status == GateStatus.YELLOW
    samples = gate.detail["rejection_samples"]
    assert samples
    assert samples[-1]["order_id"] == "bad-1"
