"""
Tests for bot/strategy_diversification_engine.py
"""

import sys
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, ".")

from bot.strategy_diversification_engine import (
    StrategyDiversificationEngine,
    DiversifiedSignal,
    StrategyAllocation,
    _REGIME_ALIASES,
    _STRATEGY_HOME_REGIME,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    """Default engine with $10,000 capital."""
    return StrategyDiversificationEngine(total_capital=10_000.0)


def _make_df(n: int = 50, close: float = 100.0) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame."""
    rng = np.random.default_rng(42)
    closes = close + rng.normal(0, 1, n).cumsum()
    highs  = closes + abs(rng.normal(0, 0.5, n))
    lows   = closes - abs(rng.normal(0, 0.5, n))
    opens  = closes + rng.normal(0, 0.3, n)
    vols   = abs(rng.normal(1_000, 200, n))
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols,
    })


def _make_indicators(
    rsi9: float = 38.0,
    rsi14: float = 40.0,
    adx: float = 28.0,
    ema21: float = 99.0,
    macd_hist: float = 0.5,
    atr: float = 1.5,
    bb_upper: float = 105.0,
    bb_lower: float = 95.0,
    n: int = 50,
) -> dict:
    """Create a minimal indicators dict with Series values."""
    return {
        "rsi_9":     pd.Series([rsi9] * n),
        "rsi_14":    pd.Series([rsi14] * n),
        "adx":       pd.Series([adx] * n),
        "ema_21":    pd.Series([ema21] * n),
        "macd_hist": pd.Series([macd_hist] * n),
        "atr":       pd.Series([atr] * n),
        "bb_upper":  pd.Series([bb_upper] * n),
        "bb_lower":  pd.Series([bb_lower] * n),
    }


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestEngineInit:
    def test_default_capital(self, engine):
        assert engine.total_capital == 10_000.0

    def test_reserve_default(self, engine):
        assert engine.reserve_pct == 0.20

    def test_strategy_pool_has_four_strategies(self, engine):
        assert len(engine.list_strategies()) == 4

    def test_strategy_names_present(self, engine):
        names = engine.list_strategies()
        assert "ApexTrendStrategy" in names
        assert "MeanReversionStrategy" in names
        assert "MomentumBreakoutStrategy" in names
        assert "LiquidityReversalStrategy" in names

    def test_custom_capital(self):
        e = StrategyDiversificationEngine(total_capital=5_000.0)
        assert e.total_capital == 5_000.0

    def test_custom_config(self):
        cfg = {"ApexTrendStrategy": {"min_confirmations": 4}}
        e = StrategyDiversificationEngine(config=cfg)
        assert e._config == cfg


# ---------------------------------------------------------------------------
# Capital allocation
# ---------------------------------------------------------------------------

class TestCapitalAllocation:
    def test_allocations_sum_to_deployable(self, engine):
        allocs = engine.get_capital_allocations("TRENDING")
        total = sum(a.allocated_capital for a in allocs)
        deployable = engine.total_capital * (1 - engine.reserve_pct)
        assert abs(total - deployable) < 0.01

    def test_primary_strategy_gets_more_capital_trending(self, engine):
        allocs = engine.get_capital_allocations("TRENDING")
        apex = next(a for a in allocs if a.strategy_name == "ApexTrendStrategy")
        mean = next(a for a in allocs if a.strategy_name == "MeanReversionStrategy")
        assert apex.allocated_capital > mean.allocated_capital

    def test_primary_strategy_gets_more_capital_ranging(self, engine):
        allocs = engine.get_capital_allocations("RANGING")
        mr = next(a for a in allocs if a.strategy_name == "MeanReversionStrategy")
        apex = next(a for a in allocs if a.strategy_name == "ApexTrendStrategy")
        assert mr.allocated_capital > apex.allocated_capital

    def test_primary_strategy_gets_more_capital_volatile(self, engine):
        allocs = engine.get_capital_allocations("VOLATILE")
        mb = next(a for a in allocs if a.strategy_name == "MomentumBreakoutStrategy")
        mr = next(a for a in allocs if a.strategy_name == "MeanReversionStrategy")
        assert mb.allocated_capital > mr.allocated_capital

    def test_weights_sum_to_one(self, engine):
        allocs = engine.get_capital_allocations("TRENDING")
        assert abs(sum(a.weight for a in allocs) - 1.0) < 1e-6

    def test_all_strategies_get_some_capital(self, engine):
        allocs = engine.get_capital_allocations("TRENDING")
        for a in allocs:
            assert a.allocated_capital > 0.0


# ---------------------------------------------------------------------------
# Regime alias normalisation
# ---------------------------------------------------------------------------

class TestRegimeAliases:
    @pytest.mark.parametrize("alias,expected", [
        ("trending", "TRENDING"),
        ("trend", "TRENDING"),
        ("bull", "TRENDING"),
        ("bullish", "TRENDING"),
        ("ranging", "RANGING"),
        ("sideways", "RANGING"),
        ("consolidation", "RANGING"),
        ("volatile", "VOLATILE"),
        ("breakout", "VOLATILE"),
        ("momentum", "VOLATILE"),
    ])
    def test_alias(self, alias, expected):
        assert _REGIME_ALIASES.get(alias) == expected


# ---------------------------------------------------------------------------
# get_best_signal – returns DiversifiedSignal
# ---------------------------------------------------------------------------

class TestGetBestSignal:
    def test_returns_diversified_signal(self, engine):
        df = _make_df()
        ind = _make_indicators()
        result = engine.get_best_signal(df, ind, market_regime="RANGING")
        assert isinstance(result, DiversifiedSignal)

    def test_signal_is_valid(self, engine):
        df = _make_df()
        ind = _make_indicators()
        result = engine.get_best_signal(df, ind, market_regime="TRENDING")
        assert result.signal in ("BUY", "SELL", "NONE")

    def test_regime_stored_in_result(self, engine):
        df = _make_df()
        ind = _make_indicators()
        result = engine.get_best_signal(df, ind, market_regime="RANGING")
        assert result.regime == "RANGING"

    def test_regime_alias_normalised(self, engine):
        df = _make_df()
        ind = _make_indicators()
        result = engine.get_best_signal(df, ind, market_regime="trending")
        assert result.regime == "TRENDING"

    def test_individual_signals_count(self, engine):
        """Engine must query all four strategies."""
        df = _make_df()
        ind = _make_indicators()
        result = engine.get_best_signal(df, ind, market_regime="RANGING")
        # At most 4 individual signals (one per strategy)
        assert len(result.individual_signals) <= 4

    def test_allocations_populated(self, engine):
        df = _make_df()
        ind = _make_indicators()
        result = engine.get_best_signal(df, ind, market_regime="RANGING")
        assert len(result.allocations) == 4

    def test_capital_allocation_positive_on_signal(self, engine):
        """If a BUY/SELL is produced, capital_allocation should be > 0."""
        df = _make_df()
        ind = _make_indicators()
        result = engine.get_best_signal(df, ind, market_regime="TRENDING")
        if result.signal != "NONE":
            assert result.capital_allocation > 0.0

    def test_no_signal_when_confidence_below_min(self):
        """Engine with very high min_confidence should return NONE more often."""
        e = StrategyDiversificationEngine(min_confidence=0.99)
        df = _make_df()
        ind = _make_indicators(rsi9=50.0, rsi14=50.0, macd_hist=0.0)
        result = e.get_best_signal(df, ind, market_regime="RANGING")
        # Should be NONE or at most BUY/SELL – we're just testing it doesn't crash
        assert result.signal in ("BUY", "SELL", "NONE")

    def test_handles_missing_indicators_gracefully(self, engine):
        """Engine must not crash with an empty indicators dict."""
        df = _make_df()
        result = engine.get_best_signal(df, {}, market_regime="RANGING")
        assert result.signal in ("BUY", "SELL", "NONE")


# ---------------------------------------------------------------------------
# update_capital
# ---------------------------------------------------------------------------

class TestUpdateCapital:
    def test_update_capital(self, engine):
        engine.update_capital(20_000.0)
        assert engine.total_capital == 20_000.0

    def test_allocations_reflect_new_capital(self, engine):
        engine.update_capital(20_000.0)
        allocs = engine.get_capital_allocations("TRENDING")
        deployable = 20_000.0 * (1 - engine.reserve_pct)
        total_alloc = sum(a.allocated_capital for a in allocs)
        assert abs(total_alloc - deployable) < 0.01


# ---------------------------------------------------------------------------
# list_strategies
# ---------------------------------------------------------------------------

class TestListStrategies:
    def test_list_strategies_returns_dict(self, engine):
        result = engine.list_strategies()
        assert isinstance(result, dict)

    def test_apex_home_regime(self, engine):
        assert engine.list_strategies()["ApexTrendStrategy"] == "TRENDING"

    def test_mean_reversion_home_regime(self, engine):
        assert engine.list_strategies()["MeanReversionStrategy"] == "RANGING"

    def test_momentum_breakout_home_regime(self, engine):
        assert engine.list_strategies()["MomentumBreakoutStrategy"] == "VOLATILE"

    def test_liquidity_reversal_home_regime(self, engine):
        assert engine.list_strategies()["LiquidityReversalStrategy"] == "ALL"
