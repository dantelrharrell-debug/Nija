"""
Tests for bot/stress_test_engine.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from stress_test_engine import (
    StressTestEngine,
    ScenarioReport,
    StressTestReport,
    PathResult,
    SAMPLE_MARKETS,
    MAX_DRAWDOWN_LIMIT,
)


class TestPathResult:
    def test_survived_no_kill_switch(self):
        pr = PathResult(
            path_id=0, scenario="FlashCrash",
            final_capital=9500, peak_capital=10000, trough_capital=9000,
            max_drawdown_pct=0.10, var_breached=False, kill_switch_triggered=False,
            num_trades=10, win_rate=0.5, total_pnl=-500,
        )
        assert pr.survived is True

    def test_not_survived_kill_switch(self):
        pr = PathResult(
            path_id=1, scenario="FlashCrash",
            final_capital=7000, peak_capital=10000, trough_capital=7000,
            max_drawdown_pct=0.30, var_breached=True, kill_switch_triggered=True,
            num_trades=5, win_rate=0.2, total_pnl=-3000,
        )
        assert pr.survived is False

    def test_not_survived_drawdown_over_limit(self):
        pr = PathResult(
            path_id=2, scenario="HighVolatility",
            final_capital=7900, peak_capital=10000, trough_capital=7900,
            max_drawdown_pct=MAX_DRAWDOWN_LIMIT + 0.01,
            var_breached=False, kill_switch_triggered=False,
            num_trades=20, win_rate=0.4, total_pnl=-2100,
        )
        assert pr.survived is False


class TestStressTestEngine:
    """Tests for the StressTestEngine class."""

    @pytest.fixture
    def engine(self):
        return StressTestEngine(
            initial_capital=10_000,
            num_paths=50,   # small for test speed
            seed=42,
        )

    def test_flash_crash_scenario_returns_report(self, engine):
        report = engine.run_flash_crash_scenario()
        assert isinstance(report, ScenarioReport)
        assert report.scenario == "FlashCrash"
        assert report.num_paths == 50

    def test_high_volatility_scenario_returns_report(self, engine):
        report = engine.run_high_volatility_scenario()
        assert isinstance(report, ScenarioReport)
        assert report.scenario == "HighVolatility"
        assert report.num_paths == 50

    def test_liquidity_drought_scenario_returns_report(self, engine):
        report = engine.run_liquidity_drought_scenario()
        assert isinstance(report, ScenarioReport)
        assert report.scenario == "LiquidityDrought"
        assert report.num_paths == 50

    def test_survival_rate_in_range(self, engine):
        for run_fn in (
            engine.run_flash_crash_scenario,
            engine.run_high_volatility_scenario,
            engine.run_liquidity_drought_scenario,
        ):
            report = run_fn()
            assert 0.0 <= report.survival_rate <= 1.0

    def test_run_all_scenarios_structure(self, engine):
        full = engine.run_all_scenarios()
        assert isinstance(full, StressTestReport)
        assert len(full.scenarios) == 3
        assert isinstance(full.overall_passed, bool)

    def test_run_all_to_dict(self, engine):
        full = engine.run_all_scenarios()
        d = full.to_dict()
        assert "timestamp" in d
        assert "scenarios" in d
        assert len(d["scenarios"]) == 3

    def test_summary_contains_scenario_names(self, engine):
        full = engine.run_all_scenarios()
        summary = full.summary()
        assert "FlashCrash" in summary
        assert "HighVolatility" in summary
        assert "LiquidityDrought" in summary

    def test_get_markets_returns_list(self, engine):
        markets = engine.get_markets()
        assert isinstance(markets, list)
        assert len(markets) > 0
        assert "BTC-USD" in markets

    def test_scenario_avg_capital_positive(self, engine):
        report = engine.run_flash_crash_scenario()
        # avg final capital should be > 0 (positions don't go below zero)
        assert report.avg_final_capital >= 0

    def test_worst_drawdown_gte_avg_drawdown(self, engine):
        report = engine.run_high_volatility_scenario()
        assert report.worst_drawdown_pct >= report.avg_max_drawdown_pct - 1e-9
