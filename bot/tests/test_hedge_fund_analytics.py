"""
Tests for bot/hedge_fund_analytics.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from hedge_fund_analytics import (
    StrategyCorrelationAnalyzer,
    LiquidityHeatmapEngine,
    HedgeFundAnalytics,
    CorrelationMatrix,
    LiquidityHeatmap,
    ScenarioSimResult,
    simulate_macro_scenario,
    get_hedge_fund_analytics,
    MACRO_EVENTS,
    HIGH_CORRELATION_THRESHOLD,
    MIN_LIQUIDITY_SCORE,
)


class TestStrategyCorrelationAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return StrategyCorrelationAnalyzer()

    def test_empty_matrix(self, analyzer):
        matrix = analyzer.compute_matrix()
        assert isinstance(matrix, CorrelationMatrix)
        assert matrix.correlations == []

    def test_records_returns(self, analyzer):
        for i in range(20):
            analyzer.record_return("ApexTrend", 0.01 * (i % 3 - 1))
        matrix = analyzer.compute_matrix()
        assert "ApexTrend" in matrix.strategies

    def test_correlation_between_identical_series_is_one(self, analyzer):
        for i in range(20):
            val = 0.01 * i
            analyzer.record_return("ApexTrend", val)
            analyzer.record_return("MomentumBreakout", val)
        matrix = analyzer.compute_matrix()
        pair = next(
            (c for c in matrix.correlations
             if {c.strategy_a, c.strategy_b} == {"ApexTrend", "MomentumBreakout"}),
            None,
        )
        assert pair is not None
        assert pair.correlation == pytest.approx(1.0, abs=0.01)
        assert pair.is_high is True
        assert ("ApexTrend", "MomentumBreakout") in matrix.high_correlation_pairs or \
               ("MomentumBreakout", "ApexTrend") in matrix.high_correlation_pairs

    def test_uncorrelated_strategies(self, analyzer):
        import random
        rng = random.Random(42)
        for i in range(30):
            analyzer.record_return("ApexTrend", rng.uniform(-0.02, 0.02))
            analyzer.record_return("MomentumBreakout", -rng.uniform(-0.02, 0.02))
        matrix = analyzer.compute_matrix()
        pair = next(
            (c for c in matrix.correlations
             if {c.strategy_a, c.strategy_b} == {"ApexTrend", "MomentumBreakout"}),
            None,
        )
        if pair:
            assert abs(pair.correlation) <= HIGH_CORRELATION_THRESHOLD

    def test_summary_contains_strategy_names(self, analyzer):
        for _ in range(15):
            analyzer.record_return("ApexTrend", 0.01)
            analyzer.record_return("MomentumBreakout", 0.01)
        matrix = analyzer.compute_matrix()
        summary = matrix.summary()
        assert "ApexTrend" in summary or "MomentumBreakout" in summary


class TestLiquidityHeatmapEngine:
    @pytest.fixture
    def engine(self):
        return LiquidityHeatmapEngine()

    def test_update_returns_cell(self, engine):
        cell = engine.update("BTC-USD", "coinbase", spread_bps=5.0, depth_usd=1_000_000)
        assert cell.symbol == "BTC-USD"
        assert cell.venue == "coinbase"
        assert 0.0 <= cell.score <= 1.0

    def test_deep_liquid_market_high_score(self, engine):
        cell = engine.update("BTC-USD", "coinbase", spread_bps=2.0, depth_usd=10_000_000)
        assert cell.score > 0.3   # should be reasonably liquid

    def test_illiquid_market_is_warning(self, engine):
        cell = engine.update("OBSCURE-USD", "coinbase", spread_bps=500.0, depth_usd=100)
        assert cell.is_warning is True
        assert cell.score < MIN_LIQUIDITY_SCORE + 0.05

    def test_heatmap_contains_cells(self, engine):
        engine.update("BTC-USD", "coinbase", 5, 1_000_000)
        engine.update("ETH-USD", "kraken", 8, 500_000)
        heatmap = engine.get_heatmap()
        assert isinstance(heatmap, LiquidityHeatmap)
        assert len(heatmap.cells) == 2

    def test_get_score_returns_value(self, engine):
        engine.update("BTC-USD", "coinbase", 5, 1_000_000)
        score = engine.get_score("BTC-USD", "coinbase")
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_get_score_unknown_returns_none(self, engine):
        assert engine.get_score("UNKNOWN", "unknown_venue") is None


class TestMacroScenarioSimulation:
    def test_known_scenario_returns_result(self):
        result = simulate_macro_scenario("crypto_market_crash", num_paths=50, rng=None)
        assert isinstance(result, ScenarioSimResult)
        assert result.scenario == "crypto_market_crash"

    def test_portfolio_impact_is_float(self):
        result = simulate_macro_scenario("fed_rate_hike", num_paths=20)
        assert isinstance(result.portfolio_impact, float)

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            simulate_macro_scenario("nonexistent_scenario")

    def test_btc_halving_rally_positive_for_trend_following(self):
        result = simulate_macro_scenario("btc_halving_rally", num_paths=100)
        # ApexTrend and MomentumBreakout should benefit
        assert result.strategy_impacts.get("ApexTrend", 0) > 0
        assert result.strategy_impacts.get("MomentumBreakout", 0) > 0

    def test_summary_method(self):
        result = simulate_macro_scenario("usd_spike", num_paths=20)
        summary = result.summary()
        assert "usd_spike" in summary
        assert "Portfolio impact" in summary


class TestHedgeFundAnalytics:
    @pytest.fixture
    def analytics(self):
        return HedgeFundAnalytics()

    def test_list_scenarios_not_empty(self, analytics):
        scenarios = analytics.list_scenarios()
        assert len(scenarios) > 0
        assert "crypto_market_crash" in scenarios

    def test_simulate_scenario(self, analytics):
        result = analytics.simulate_scenario("exchange_hack")
        assert isinstance(result, ScenarioSimResult)

    def test_full_report_is_string(self, analytics):
        # Add some data first
        analytics.correlation_analyzer.record_return("ApexTrend", 0.01)
        report = analytics.full_report()
        assert isinstance(report, str)
        assert "NIJA HEDGE FUND ANALYTICS" in report

    def test_singleton(self):
        a = get_hedge_fund_analytics()
        b = get_hedge_fund_analytics()
        assert a is b
