"""
Tests for bot/portfolio_risk_tuner.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from portfolio_risk_tuner import (
    AllocationLimits,
    StrategyQuorum,
    PortfolioRiskConstraints,
    PortfolioRiskTuner,
    get_portfolio_risk_tuner,
    TunerSnapshot,
    MIN_STRATEGY_WEIGHT,
    MAX_STRATEGY_WEIGHT,
)


class TestAllocationLimits:
    def test_asset_within_cap_allowed(self):
        limits = AllocationLimits(max_per_asset_pct=0.10)
        ok, reason = limits.check_asset(0.05, "BTC-USD")
        assert ok is True
        assert reason == ""

    def test_asset_over_cap_rejected(self):
        limits = AllocationLimits(max_per_asset_pct=0.10)
        ok, reason = limits.check_asset(0.15, "BTC-USD")
        assert ok is False
        assert "BTC-USD" in reason

    def test_strategy_within_cap_allowed(self):
        limits = AllocationLimits(max_per_strategy_pct=0.40)
        ok, _ = limits.check_strategy(0.35, "ApexTrend")
        assert ok is True

    def test_strategy_over_cap_rejected(self):
        limits = AllocationLimits(max_per_strategy_pct=0.40)
        ok, reason = limits.check_strategy(0.50, "ApexTrend")
        assert ok is False
        assert "ApexTrend" in reason


class TestStrategyQuorum:
    def test_quorum_met_with_enough_signals(self):
        quorum = StrategyQuorum(required_count=2, min_confidence=0.65)
        signals = {"ApexTrend": 0.80, "MomentumBreakout": 0.70, "MeanReversion": 0.40}
        met, count = quorum.is_met(signals)
        assert met is True
        assert count == 2

    def test_quorum_not_met_insufficient_signals(self):
        quorum = StrategyQuorum(required_count=3, min_confidence=0.65)
        signals = {"ApexTrend": 0.80, "MomentumBreakout": 0.70}
        met, count = quorum.is_met(signals)
        assert met is False
        assert count == 2

    def test_quorum_met_all_qualify(self):
        quorum = StrategyQuorum(required_count=2, min_confidence=0.50)
        signals = {"ApexTrend": 0.60, "MomentumBreakout": 0.55}
        met, count = quorum.is_met(signals)
        assert met is True
        assert count == 2

    def test_empty_signals_not_met(self):
        quorum = StrategyQuorum(required_count=1, min_confidence=0.65)
        met, count = quorum.is_met({})
        assert met is False
        assert count == 0


class TestPortfolioRiskConstraints:
    def test_normal_conditions_allowed(self):
        constraints = PortfolioRiskConstraints(
            var_99_hard_limit=0.08, max_drawdown_hard_limit=0.20
        )
        ok, reason = constraints.check(current_var_99=0.04, current_drawdown=0.10)
        assert ok is True

    def test_var_breach_halts(self):
        constraints = PortfolioRiskConstraints(var_99_hard_limit=0.08)
        ok, reason = constraints.check(current_var_99=0.09, current_drawdown=0.05)
        assert ok is False
        assert "VaR" in reason

    def test_drawdown_breach_halts(self):
        constraints = PortfolioRiskConstraints(max_drawdown_hard_limit=0.20)
        ok, reason = constraints.check(current_var_99=0.03, current_drawdown=0.25)
        assert ok is False
        assert "Drawdown" in reason

    def test_recovery_thresholds_set(self):
        constraints = PortfolioRiskConstraints(
            var_99_hard_limit=0.08, max_drawdown_hard_limit=0.20
        )
        assert constraints.var_99_recovery == pytest.approx(0.06, rel=0.01)
        assert constraints.drawdown_recovery == pytest.approx(0.15, rel=0.01)


class TestPortfolioRiskTuner:
    @pytest.fixture
    def tuner(self):
        return PortfolioRiskTuner()

    def test_approve_entry_normal_conditions(self, tuner):
        approved, reason = tuner.approve_entry(
            asset="BTC-USD",
            strategy="ApexTrend",
            proposed_asset_pct=0.05,
            proposed_strategy_pct=0.30,
            strategy_signals={"ApexTrend": 0.80, "MomentumBreakout": 0.75},
        )
        assert approved is True

    def test_approve_entry_asset_cap_exceeded(self, tuner):
        approved, reason = tuner.approve_entry(
            asset="BTC-USD",
            strategy="ApexTrend",
            proposed_asset_pct=0.20,        # exceeds 10% cap
            proposed_strategy_pct=0.30,
            strategy_signals={"ApexTrend": 0.80, "MomentumBreakout": 0.75},
        )
        assert approved is False

    def test_approve_entry_quorum_not_met(self, tuner):
        approved, reason = tuner.approve_entry(
            asset="ETH-USD",
            strategy="MeanReversion",
            proposed_asset_pct=0.05,
            proposed_strategy_pct=0.20,
            strategy_signals={"MeanReversion": 0.40},  # below min_confidence
        )
        assert approved is False
        assert "Quorum" in reason

    def test_update_risk_metrics_triggers_halt(self, tuner):
        allowed, reason = tuner.update_risk_metrics(var_99=0.09, drawdown=0.05)
        assert allowed is False
        assert tuner.is_halted() is True

    def test_update_risk_metrics_normal_no_halt(self, tuner):
        allowed, _ = tuner.update_risk_metrics(var_99=0.03, drawdown=0.05)
        assert allowed is True
        assert tuner.is_halted() is False

    def test_strategy_weights_clamped(self, tuner):
        tuner.update_strategy_weights({
            "ApexTrend": 0.90,      # clamped to MAX_STRATEGY_WEIGHT
            "MomentumBreakout": 0.01,  # clamped to MIN_STRATEGY_WEIGHT
        })
        assert tuner.get_strategy_weight("ApexTrend") <= MAX_STRATEGY_WEIGHT
        assert tuner.get_strategy_weight("MomentumBreakout") >= MIN_STRATEGY_WEIGHT

    def test_snapshot_returns_tuner_snapshot(self, tuner):
        snap = tuner.snapshot()
        assert isinstance(snap, TunerSnapshot)
        assert snap.trading_allowed is True

    def test_halted_entry_rejected(self, tuner):
        tuner.update_risk_metrics(var_99=0.20, drawdown=0.50)  # extreme breach
        approved, reason = tuner.approve_entry(
            asset="BTC-USD",
            strategy="ApexTrend",
            proposed_asset_pct=0.05,
            proposed_strategy_pct=0.30,
            strategy_signals={"ApexTrend": 0.80, "MomentumBreakout": 0.75},
        )
        assert approved is False
        assert "HALTED" in reason

    def test_singleton(self):
        a = get_portfolio_risk_tuner()
        b = get_portfolio_risk_tuner()
        assert a is b
