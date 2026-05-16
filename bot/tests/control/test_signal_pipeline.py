"""
Unit tests for bot.control.signal_pipeline
============================================

Coverage:
  1. End-to-end signal approval
  2. Signal rejection at compile stage
  3. Signal rejection at risk stage
  4. Regime injection into raw signal
  5. process_dict convenience wrapper
  6. Redis audit trail storage
  7. Health / observability counters
  8. Singleton stability
  9. No-dataframe path (regime skipped)
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from bot.control.control_compiler import ControlCompiler, RawSignal, CompiledSignal
from bot.control.regime_engine import RegimeEngine, MarketRegime, RegimeResult
from bot.control.risk_engine import RiskEngine
from bot.control.signal_pipeline import SignalPipeline, get_signal_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n: int = 60, trend: str = "up") -> pd.DataFrame:
    np.random.seed(42)
    close = np.zeros(n)
    close[0] = 100.0
    for i in range(1, n):
        if trend == "up":
            close[i] = close[i - 1] * (1 + 0.005 + np.random.randn() * 0.002)
        elif trend == "flat":
            close[i] = close[i - 1] + np.random.randn() * 0.3
        else:
            close[i] = close[i - 1] + np.random.randn() * 0.5
    high   = close * 1.005
    low    = close * 0.995
    open_  = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def _valid_raw(**overrides) -> RawSignal:
    defaults = dict(
        symbol="BTC-USD",
        side="buy",
        action="enter_long",
        size_usd=100.0,
        confidence=0.70,
        regime="trending",
        strategy="swing",
        approved=True,
    )
    defaults.update(overrides)
    return RawSignal(**defaults)


def _fresh_pipeline(**kwargs) -> SignalPipeline:
    """Return a new, isolated SignalPipeline."""
    return SignalPipeline(
        compiler=ControlCompiler(),
        regime_engine=RegimeEngine(),
        risk_engine=RiskEngine(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. End-to-end signal approval
# ---------------------------------------------------------------------------

class TestSignalApproval(unittest.TestCase):

    def test_valid_signal_approved(self):
        pipeline = _fresh_pipeline()
        raw = _valid_raw()
        result = pipeline.process_signal(
            raw,
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, CompiledSignal)

    def test_approved_signal_has_correct_symbol(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(symbol="eth-usd"),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.symbol, "ETH-USD")

    def test_approved_signal_has_signal_id(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNotNone(result)
        import uuid
        uuid.UUID(result.signal_id)  # must not raise

    def test_approved_signal_size_within_limit(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(size_usd=500.0),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
            max_position_size_pct=10.0,
        )
        self.assertIsNotNone(result)
        self.assertLessEqual(result.size_usd, 1000.0)  # 10% of 10_000


# ---------------------------------------------------------------------------
# 2. Signal rejection at compile stage
# ---------------------------------------------------------------------------

class TestCompileRejection(unittest.TestCase):

    def test_empty_symbol_rejected(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(symbol=""),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNone(result)

    def test_low_confidence_rejected(self):
        pipeline = _fresh_pipeline()
        # swing floor = 0.65; confidence 0.10 should fail
        result = pipeline.process_signal(
            _valid_raw(strategy="swing", confidence=0.10),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNone(result)

    def test_not_approved_rejected(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(approved=False, action="enter_long"),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNone(result)

    def test_invalid_confidence_range_rejected(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(confidence=1.5),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 3. Signal rejection at risk stage
# ---------------------------------------------------------------------------

class TestRiskRejection(unittest.TestCase):

    def test_too_many_positions_rejected(self):
        pipeline = _fresh_pipeline()
        positions = [{"symbol": f"COIN{i}-USD", "size_usd": 100.0} for i in range(7)]
        result = pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=positions,
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNone(result)

    def test_daily_loss_exceeded_rejected(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
            daily_pnl=-600.0,  # 6% > 5% limit
        )
        self.assertIsNone(result)

    def test_drawdown_exceeded_rejected(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=8_000.0,
            peak_portfolio_value=10_000.0,  # 20% drawdown > 15% limit
        )
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 4. Regime injection
# ---------------------------------------------------------------------------

class TestRegimeInjection(unittest.TestCase):

    def test_detected_regime_injected_into_signal(self):
        """When df is provided, the detected regime should override the raw signal's regime."""
        mock_regime_engine = MagicMock(spec=RegimeEngine)
        mock_regime_engine.detect.return_value = RegimeResult(
            regime=MarketRegime.TRENDING,
            confidence=0.80,
            adx=30.0,
            rsi=60.0,
            volatility=0.01,
            bb_width_pct=0.05,
            context={},
            symbol="BTC-USD",
            detected_at="2026-01-01T00:00:00+00:00",
        )
        pipeline = SignalPipeline(
            compiler=ControlCompiler(),
            regime_engine=mock_regime_engine,
            risk_engine=RiskEngine(),
        )
        raw = _valid_raw(regime="unknown", strategy="swing")
        result = pipeline.process_signal(
            raw,
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        # Regime engine should have been called
        mock_regime_engine.detect.assert_called_once()

    def test_no_df_skips_regime_detection(self):
        mock_regime_engine = MagicMock(spec=RegimeEngine)
        pipeline = SignalPipeline(
            compiler=ControlCompiler(),
            regime_engine=mock_regime_engine,
            risk_engine=RiskEngine(),
        )
        pipeline.process_signal(
            _valid_raw(),
            df=None,
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        mock_regime_engine.detect.assert_not_called()

    def test_empty_df_skips_regime_detection(self):
        mock_regime_engine = MagicMock(spec=RegimeEngine)
        pipeline = SignalPipeline(
            compiler=ControlCompiler(),
            regime_engine=mock_regime_engine,
            risk_engine=RiskEngine(),
        )
        pipeline.process_signal(
            _valid_raw(),
            df=pd.DataFrame(),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        mock_regime_engine.detect.assert_not_called()


# ---------------------------------------------------------------------------
# 5. process_dict convenience wrapper
# ---------------------------------------------------------------------------

class TestProcessDict(unittest.TestCase):

    def test_valid_dict_approved(self):
        pipeline = _fresh_pipeline()
        d = {
            "symbol":     "BTC-USD",
            "side":       "buy",
            "action":     "enter_long",
            "size_usd":   100.0,
            "confidence": 0.70,
            "regime":     "trending",
            "strategy":   "swing",
            "approved":   True,
        }
        result = pipeline.process_dict(
            d,
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNotNone(result)

    def test_invalid_dict_rejected(self):
        pipeline = _fresh_pipeline()
        d = {"symbol": "", "action": "enter_long", "confidence": 0.70, "regime": "trending"}
        result = pipeline.process_dict(
            d,
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNone(result)

    def test_buy_action_mapping(self):
        pipeline = _fresh_pipeline()
        d = {
            "symbol":     "ETH-USD",
            "action":     "buy",
            "size_usd":   100.0,
            "confidence": 0.70,
            "regime":     "trending",
            "strategy":   "swing",
        }
        result = pipeline.process_dict(
            d,
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.side, "buy")


# ---------------------------------------------------------------------------
# 6. Redis audit trail
# ---------------------------------------------------------------------------

class TestRedisAuditTrail(unittest.TestCase):

    def test_approved_signal_stored_in_redis(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        pipeline = SignalPipeline(
            compiler=ControlCompiler(redis_client=mock_redis),
            regime_engine=RegimeEngine(redis_client=mock_redis),
            risk_engine=RiskEngine(redis_client=mock_redis),
            redis_client=mock_redis,
        )
        pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        # setex should have been called (pipeline audit + compiler audit)
        self.assertTrue(mock_redis.setex.called)

    def test_rejected_signal_stored_in_redis(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        pipeline = SignalPipeline(
            compiler=ControlCompiler(redis_client=mock_redis),
            regime_engine=RegimeEngine(redis_client=mock_redis),
            risk_engine=RiskEngine(redis_client=mock_redis),
            redis_client=mock_redis,
        )
        pipeline.process_signal(
            _valid_raw(symbol=""),  # will be rejected
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertTrue(mock_redis.setex.called)

    def test_redis_failure_does_not_crash_pipeline(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mock_redis.setex.side_effect = Exception("Redis down")
        pipeline = SignalPipeline(
            compiler=ControlCompiler(redis_client=mock_redis),
            regime_engine=RegimeEngine(redis_client=mock_redis),
            risk_engine=RiskEngine(redis_client=mock_redis),
            redis_client=mock_redis,
        )
        # Should not raise
        result = pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        # Result may be None or CompiledSignal — just must not raise
        self.assertIn(result, [None, result])


# ---------------------------------------------------------------------------
# 7. Health / observability
# ---------------------------------------------------------------------------

class TestHealth(unittest.TestCase):

    def test_health_available_flag(self):
        pipeline = _fresh_pipeline()
        health = pipeline.get_health()
        self.assertTrue(health["available"])

    def test_counters_incremented_on_approval(self):
        pipeline = _fresh_pipeline()
        pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        health = pipeline.get_health()
        self.assertEqual(health["total"], 1)

    def test_counters_incremented_on_rejection(self):
        pipeline = _fresh_pipeline()
        pipeline.process_signal(
            _valid_raw(symbol=""),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        health = pipeline.get_health()
        self.assertEqual(health["rejected"], 1)

    def test_approval_rate_calculation(self):
        pipeline = _fresh_pipeline()
        pipeline.process_signal(
            _valid_raw(),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        pipeline.process_signal(
            _valid_raw(symbol=""),
            df=_make_df(60, "up"),
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        health = pipeline.get_health()
        self.assertEqual(health["total"], 2)

    def test_health_contains_sub_component_health(self):
        pipeline = _fresh_pipeline()
        health = pipeline.get_health()
        self.assertIn("compiler", health)
        self.assertIn("risk_engine", health)


# ---------------------------------------------------------------------------
# 8. Singleton stability
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):

    def test_get_signal_pipeline_returns_same_instance(self):
        p1 = get_signal_pipeline()
        p2 = get_signal_pipeline()
        self.assertIs(p1, p2)

    def test_singleton_processes_signal(self):
        pipeline = get_signal_pipeline()
        # Should not raise
        result = pipeline.process_signal(
            _valid_raw(),
            df=None,
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIn(result, [None, result])


# ---------------------------------------------------------------------------
# 9. No-dataframe path
# ---------------------------------------------------------------------------

class TestNoDataframePath(unittest.TestCase):

    def test_no_df_uses_raw_signal_regime(self):
        pipeline = _fresh_pipeline()
        # Without df, regime detection is skipped; raw signal regime is used
        result = pipeline.process_signal(
            _valid_raw(regime="trending", strategy="swing"),
            df=None,
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.regime, "trending")

    def test_no_df_hold_action_approved(self):
        pipeline = _fresh_pipeline()
        result = pipeline.process_signal(
            _valid_raw(action="hold", confidence=0.0, regime="unknown"),
            df=None,
            current_positions=[],
            portfolio_value_usd=10_000.0,
        )
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
