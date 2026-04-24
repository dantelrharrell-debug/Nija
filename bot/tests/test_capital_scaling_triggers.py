"""
Tests for bot/capital_scaling_triggers.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Allow imports from bot/
sys.path.insert(0, str(Path(__file__).parent.parent))

from capital_scaling_triggers import (
    CapitalScalingTrigger,
    ScaleDecision,
    TriggerConfig,
    get_capital_scaling_trigger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trigger(
    base_capital: float = 10_000.0,
    sharpe_threshold: float = 1.5,
    max_drawdown_pct: float = 5.0,
    cooldown_trades: int = 5,
    max_scale_factor: float = 2.0,
    scale_increment: float = 0.10,
) -> CapitalScalingTrigger:
    """Return a fresh trigger (not singleton) with controllable thresholds."""
    cfg = TriggerConfig(
        sharpe_threshold=sharpe_threshold,
        max_drawdown_pct=max_drawdown_pct,
        cooldown_trades=cooldown_trades,
        max_scale_factor=max_scale_factor,
        scale_increment=scale_increment,
    )
    # Patch audit log writes so tests don't create files
    with patch("capital_scaling_triggers.AUDIT_LOG", Path("/tmp/test_cst_audit.jsonl")):
        return CapitalScalingTrigger(base_capital=base_capital, config=cfg, window=20)


def _feed_profitable(
    trigger: CapitalScalingTrigger,
    n: int,
    pnl: float = 120.0,
    start_capital: float = 10_000.0,
) -> ScaleDecision:
    """Feed n profitable trades and return the last decision."""
    capital = start_capital
    decision = None
    for _ in range(n):
        capital += pnl
        decision = trigger.record_trade(pnl_usd=pnl, is_win=True, current_capital=capital)
    return decision  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Gate 1: Sharpe threshold
# ---------------------------------------------------------------------------


class TestSharpeGate:
    def test_blocked_when_sharpe_below_threshold(self) -> None:
        # High threshold that will never be reached without enough variation
        trigger = _make_trigger(sharpe_threshold=1000.0, cooldown_trades=0)
        # Feed a mix of big wins and big losses — low Sharpe
        capital = 10_000.0
        for i in range(20):
            pnl = 500.0 if i % 2 == 0 else -499.0
            capital += pnl
            d = trigger.record_trade(pnl_usd=pnl, is_win=(pnl > 0), current_capital=capital)

        # Most decisions should be blocked on Sharpe
        assert d.approved is False
        assert "Sharpe" in d.reason

    def test_approved_when_sharpe_above_threshold(self) -> None:
        # Very low Sharpe requirement so consistent wins pass easily
        trigger = _make_trigger(sharpe_threshold=0.01, cooldown_trades=3)
        # 10 consistent wins → high Sharpe, low drawdown
        decision = _feed_profitable(trigger, 10)
        assert decision.approved is True


# ---------------------------------------------------------------------------
# Gate 2: Drawdown gate
# ---------------------------------------------------------------------------


class TestDrawdownGate:
    def test_blocked_when_drawdown_exceeds_max(self) -> None:
        trigger = _make_trigger(
            sharpe_threshold=0.01,
            max_drawdown_pct=5.0,
            cooldown_trades=3,
        )
        # First build a peak
        capital = 10_000.0
        for _ in range(10):
            capital += 120.0
            trigger.record_trade(120.0, True, capital)

        # Then drop below the 5 % drawdown threshold
        capital -= capital * 0.06  # 6 % drop → above 5 % limit
        decision = trigger.check_triggers(capital)

        assert decision.approved is False
        assert "Drawdown" in decision.reason or "drawdown" in decision.reason.lower()

    def test_approved_when_drawdown_within_limit(self) -> None:
        trigger = _make_trigger(
            sharpe_threshold=0.01,
            max_drawdown_pct=10.0,
            cooldown_trades=5,
        )
        decision = _feed_profitable(trigger, 10, pnl=50.0)
        # No drawdown occurred → should pass drawdown gate
        assert decision.drawdown_pct == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Gate 3: Cooldown gate
# ---------------------------------------------------------------------------


class TestCooldownGate:
    def test_blocked_before_cooldown_expires(self) -> None:
        trigger = _make_trigger(
            sharpe_threshold=0.01,
            max_drawdown_pct=50.0,
            cooldown_trades=10,
        )
        # Feed only 5 trades — below cooldown of 10
        capital = 10_000.0
        decision = None
        for _ in range(5):
            capital += 120.0
            decision = trigger.record_trade(120.0, True, capital)

        assert decision.approved is False
        assert "Cooldown" in decision.reason or "cooldown" in decision.reason.lower()

    def test_approved_after_cooldown_expires(self) -> None:
        trigger = _make_trigger(
            sharpe_threshold=0.01,
            max_drawdown_pct=50.0,
            cooldown_trades=5,
        )
        decision = _feed_profitable(trigger, 10)
        assert decision.approved is True
        assert trigger.trades_since_last_scale == 0   # reset after approval

    def test_cooldown_resets_after_approval(self) -> None:
        trigger = _make_trigger(
            sharpe_threshold=0.01,
            max_drawdown_pct=50.0,
            cooldown_trades=5,
        )
        _feed_profitable(trigger, 10)           # first scale-up
        # Now only 1 new trade → below cooldown again
        decision = trigger.record_trade(120.0, True, trigger._current_capital + 120.0)
        assert decision.approved is False

    def test_trades_since_last_scale_property(self) -> None:
        trigger = _make_trigger(cooldown_trades=5)
        assert trigger.trades_since_last_scale == 0
        trigger.record_trade(100.0, True, 10_100.0)
        assert trigger.trades_since_last_scale == 1


# ---------------------------------------------------------------------------
# Gate 4: Max-scale cap
# ---------------------------------------------------------------------------


class TestMaxScaleCap:
    def test_blocked_at_max_scale_factor(self) -> None:
        trigger = _make_trigger(
            sharpe_threshold=0.01,
            max_drawdown_pct=50.0,
            cooldown_trades=5,
            max_scale_factor=1.10,   # cap at 10 % above base
            scale_increment=0.10,    # so one approval reaches the cap
        )
        # First batch → scale-up to 1.10×
        _feed_profitable(trigger, 10)
        # Second batch — already at cap
        capital = trigger._current_capital
        second = _feed_profitable(trigger, 10, start_capital=capital)
        assert second.approved is False
        assert "maximum" in second.reason.lower()

    def test_allocated_capital_does_not_exceed_cap(self) -> None:
        trigger = _make_trigger(
            sharpe_threshold=0.01,
            max_drawdown_pct=50.0,
            cooldown_trades=5,
            max_scale_factor=2.0,
            scale_increment=0.10,
        )
        # Drive 100 profitable trades; allocated should never exceed 2× base
        capital = 10_000.0
        for _ in range(100):
            capital += 120.0
            trigger.record_trade(120.0, True, capital)

        assert trigger.allocated_capital <= trigger.base_capital * 2.0


# ---------------------------------------------------------------------------
# Properties and status
# ---------------------------------------------------------------------------


class TestProperties:
    def test_allocated_capital_starts_at_base(self) -> None:
        trigger = _make_trigger(base_capital=5_000.0)
        assert trigger.allocated_capital == pytest.approx(5_000.0)

    def test_drawdown_pct_zero_when_no_losses(self) -> None:
        trigger = _make_trigger()
        trigger.record_trade(100.0, True, 10_100.0)
        assert trigger.current_drawdown_pct == pytest.approx(0.0)

    def test_drawdown_increases_after_loss(self) -> None:
        trigger = _make_trigger()
        trigger.record_trade(200.0, True, 10_200.0)   # peak = 10_200
        trigger.record_trade(-300.0, False, 9_900.0)  # drop from peak
        expected_dd = (10_200.0 - 9_900.0) / 10_200.0 * 100.0
        assert trigger.current_drawdown_pct == pytest.approx(expected_dd, abs=0.01)

    def test_get_status_keys(self) -> None:
        trigger = _make_trigger()
        status = trigger.get_status()
        for key in (
            "base_capital",
            "allocated_capital",
            "scale_factor",
            "current_capital",
            "drawdown_pct",
            "sharpe_ratio",
            "trades_since_last_scale",
            "total_scale_events",
        ):
            assert key in status


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def test_report_is_string(self) -> None:
        trigger = _make_trigger()
        assert isinstance(trigger.get_report(), str)

    def test_report_contains_key_info(self) -> None:
        trigger = _make_trigger(base_capital=7_500.0)
        report = trigger.get_report()
        assert "7,500" in report or "7500" in report
        assert "Sharpe" in report
        assert "Drawdown" in report


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        a = get_capital_scaling_trigger(base_capital=1_000.0, reset=True)
        b = get_capital_scaling_trigger()
        assert a is b

    def test_reset_creates_new_instance(self) -> None:
        a = get_capital_scaling_trigger(base_capital=1_000.0, reset=True)
        b = get_capital_scaling_trigger(base_capital=2_000.0, reset=True)
        assert a is not b
