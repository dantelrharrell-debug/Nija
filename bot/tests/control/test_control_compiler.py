"""
Unit tests for bot.control.control_compiler
============================================

Coverage:
  1. Schema validation — missing / wrong-type fields
  2. Confidence validation — range, strategy floor
  3. Regime compatibility — strategy vs regime
  4. Position sizing — cap enforcement
  5. Execution readiness — approved flag
  6. Normalisation — symbol, side, regime casing
  7. compile_dict convenience wrapper
  8. Health / observability counters
  9. Singleton stability
"""

import math
import unittest

from bot.control.control_compiler import (
    ControlCompiler,
    CompiledSignal,
    RawSignal,
    get_control_compiler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_raw(**overrides) -> RawSignal:
    """Return a minimal valid execution signal with optional overrides."""
    defaults = dict(
        symbol="BTC-USD",
        side="buy",
        action="enter_long",
        size_usd=100.0,
        confidence=0.65,
        regime="trending",
        strategy="swing",
        approved=True,
    )
    defaults.update(overrides)
    return RawSignal(**defaults)


def _fresh_compiler() -> ControlCompiler:
    """Return a new, isolated ControlCompiler (not the process singleton)."""
    return ControlCompiler()


# ---------------------------------------------------------------------------
# 1. Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_valid_signal_accepted(self):
        compiled, notes = self.compiler.compile(_valid_raw())
        self.assertIsNotNone(compiled)
        self.assertIsInstance(compiled, CompiledSignal)

    def test_empty_symbol_rejected(self):
        compiled, notes = self.compiler.compile(_valid_raw(symbol=""))
        self.assertIsNone(compiled)
        self.assertTrue(any("schema_invalid" in n for n in notes))

    def test_whitespace_symbol_rejected(self):
        compiled, notes = self.compiler.compile(_valid_raw(symbol="   "))
        self.assertIsNone(compiled)

    def test_non_numeric_size_rejected(self):
        raw = _valid_raw()
        raw.size_usd = "large"  # type: ignore[assignment]
        compiled, notes = self.compiler.compile(raw)
        self.assertIsNone(compiled)
        self.assertTrue(any("schema_invalid" in n for n in notes))

    def test_non_numeric_confidence_rejected(self):
        raw = _valid_raw()
        raw.confidence = None  # type: ignore[assignment]
        compiled, notes = self.compiler.compile(raw)
        self.assertIsNone(compiled)
        self.assertTrue(any("schema_invalid" in n for n in notes))

    def test_infinite_size_rejected(self):
        compiled, notes = self.compiler.compile(_valid_raw(size_usd=math.inf))
        self.assertIsNone(compiled)

    def test_nan_size_rejected(self):
        compiled, notes = self.compiler.compile(_valid_raw(size_usd=math.nan))
        self.assertIsNone(compiled)

    def test_nan_confidence_rejected(self):
        compiled, notes = self.compiler.compile(_valid_raw(confidence=math.nan))
        self.assertIsNone(compiled)


# ---------------------------------------------------------------------------
# 2. Confidence validation
# ---------------------------------------------------------------------------

class TestConfidenceValidation(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_confidence_above_1_rejected(self):
        compiled, notes = self.compiler.compile(_valid_raw(confidence=1.5))
        self.assertIsNone(compiled)
        self.assertTrue(any("confidence_invalid" in n for n in notes))

    def test_confidence_below_0_rejected(self):
        compiled, notes = self.compiler.compile(_valid_raw(confidence=-0.1))
        self.assertIsNone(compiled)
        self.assertTrue(any("confidence_invalid" in n for n in notes))

    def test_confidence_exactly_0_accepted_for_hold(self):
        # hold is not an execution action — no floor check
        compiled, notes = self.compiler.compile(_valid_raw(action="hold", confidence=0.0))
        self.assertIsNotNone(compiled)

    def test_swing_strategy_below_floor_rejected(self):
        # swing floor = 0.50; confidence 0.49 should fail
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="swing", confidence=0.49, action="enter_long")
        )
        self.assertIsNone(compiled)
        self.assertTrue(any("confidence_invalid" in n for n in notes))

    def test_scalp_strategy_above_floor_accepted(self):
        # scalp floor = 0.30; confidence 0.35 should pass
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="scalp", confidence=0.35, action="enter_long")
        )
        self.assertIsNotNone(compiled)

    def test_default_strategy_floor_applied(self):
        # default floor = 0.25; confidence 0.10 should fail for execution
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="unknown_strategy", confidence=0.10, action="enter_long")
        )
        self.assertIsNone(compiled)

    def test_confidence_exactly_at_floor_accepted(self):
        # swing floor = 0.50; exactly 0.50 should pass
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="swing", confidence=0.50, action="enter_long")
        )
        self.assertIsNotNone(compiled)


# ---------------------------------------------------------------------------
# 3. Regime compatibility
# ---------------------------------------------------------------------------

class TestRegimeCompatibility(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_swing_in_trending_accepted(self):
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="swing", regime="trending")
        )
        self.assertIsNotNone(compiled)

    def test_scalp_in_ranging_accepted(self):
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="scalp", regime="ranging", confidence=0.35)
        )
        self.assertIsNotNone(compiled)

    def test_mean_reversion_in_mean_reversion_accepted(self):
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="mean_reversion", regime="mean_reversion", confidence=0.30)
        )
        self.assertIsNotNone(compiled)

    def test_swing_in_ranging_rejected(self):
        # swing is not in ranging compatible list
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="swing", regime="ranging")
        )
        self.assertIsNone(compiled)
        self.assertTrue(any("regime_incompatible" in n for n in notes))

    def test_unknown_regime_accepts_any_strategy(self):
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="swing", regime="unknown")
        )
        self.assertIsNotNone(compiled)

    def test_empty_strategy_skips_regime_check(self):
        compiled, notes = self.compiler.compile(
            _valid_raw(strategy="", regime="ranging", confidence=0.30)
        )
        self.assertIsNotNone(compiled)

    def test_non_execution_action_skips_regime_check(self):
        # hold action should not be blocked by regime incompatibility
        compiled, notes = self.compiler.compile(
            _valid_raw(action="hold", strategy="swing", regime="ranging", confidence=0.0)
        )
        self.assertIsNotNone(compiled)


# ---------------------------------------------------------------------------
# 4. Position sizing
# ---------------------------------------------------------------------------

class TestPositionSizing(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_size_within_limit_unchanged(self):
        # 100 USD out of 10_000 = 1% — well within 10% limit
        compiled, notes = self.compiler.compile(
            _valid_raw(size_usd=100.0),
            portfolio_value_usd=10_000.0,
            max_position_size_pct=10.0,
        )
        self.assertIsNotNone(compiled)
        self.assertAlmostEqual(compiled.size_usd, 100.0)

    def test_size_exceeding_limit_capped(self):
        # 2000 USD out of 10_000 = 20% — exceeds 10% limit → capped to 1000
        compiled, notes = self.compiler.compile(
            _valid_raw(size_usd=2000.0),
            portfolio_value_usd=10_000.0,
            max_position_size_pct=10.0,
        )
        self.assertIsNotNone(compiled)
        self.assertAlmostEqual(compiled.size_usd, 1000.0)
        self.assertTrue(any("size_capped" in n for n in notes))

    def test_size_exactly_at_limit_unchanged(self):
        compiled, notes = self.compiler.compile(
            _valid_raw(size_usd=1000.0),
            portfolio_value_usd=10_000.0,
            max_position_size_pct=10.0,
        )
        self.assertIsNotNone(compiled)
        self.assertAlmostEqual(compiled.size_usd, 1000.0)

    def test_zero_portfolio_value_no_cap(self):
        # With zero portfolio value, sizing is skipped
        compiled, notes = self.compiler.compile(
            _valid_raw(size_usd=9999.0),
            portfolio_value_usd=0.0,
            max_position_size_pct=10.0,
        )
        self.assertIsNotNone(compiled)
        self.assertAlmostEqual(compiled.size_usd, 9999.0)


# ---------------------------------------------------------------------------
# 5. Execution readiness
# ---------------------------------------------------------------------------

class TestExecutionReadiness(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_approved_true_accepted(self):
        compiled, notes = self.compiler.compile(_valid_raw(approved=True))
        self.assertIsNotNone(compiled)

    def test_approved_false_execution_rejected(self):
        compiled, notes = self.compiler.compile(
            _valid_raw(approved=False, action="enter_long")
        )
        self.assertIsNone(compiled)
        self.assertTrue(any("not_approved" in n for n in notes))

    def test_approved_false_hold_accepted(self):
        # hold is not an execution action — approved=False is fine
        compiled, notes = self.compiler.compile(
            _valid_raw(approved=False, action="hold", confidence=0.0)
        )
        self.assertIsNotNone(compiled)


# ---------------------------------------------------------------------------
# 6. Normalisation
# ---------------------------------------------------------------------------

class TestNormalisation(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_symbol_uppercased(self):
        compiled, _ = self.compiler.compile(_valid_raw(symbol="btc-usd"))
        self.assertIsNotNone(compiled)
        self.assertEqual(compiled.symbol, "BTC-USD")

    def test_regime_lowercased(self):
        compiled, _ = self.compiler.compile(_valid_raw(regime="Trending"))
        self.assertIsNotNone(compiled)
        self.assertEqual(compiled.regime, "trending")

    def test_long_side_normalised_to_buy(self):
        compiled, _ = self.compiler.compile(_valid_raw(side="long", action="enter_long"))
        self.assertIsNotNone(compiled)
        self.assertEqual(compiled.side, "buy")

    def test_short_side_normalised_to_sell(self):
        compiled, _ = self.compiler.compile(
            _valid_raw(side="short", action="enter_short", confidence=0.65)
        )
        self.assertIsNotNone(compiled)
        self.assertEqual(compiled.side, "sell")

    def test_compiled_at_populated(self):
        compiled, _ = self.compiler.compile(_valid_raw())
        self.assertIsNotNone(compiled)
        self.assertIn("T", compiled.compiled_at)

    def test_signal_id_is_uuid(self):
        compiled, _ = self.compiler.compile(_valid_raw())
        self.assertIsNotNone(compiled)
        import uuid
        # Should not raise
        uuid.UUID(compiled.signal_id)

    def test_to_pipeline_kwargs_keys(self):
        compiled, _ = self.compiler.compile(_valid_raw(symbol="ETH-USD", strategy="swing"))
        self.assertIsNotNone(compiled)
        kwargs = compiled.to_pipeline_kwargs()
        for key in ("symbol", "side", "size_usd", "strategy", "account_id"):
            self.assertIn(key, kwargs)
        self.assertEqual(kwargs["symbol"], "ETH-USD")


# ---------------------------------------------------------------------------
# 7. compile_dict convenience wrapper
# ---------------------------------------------------------------------------

class TestCompileDict(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_compile_dict_valid(self):
        d = {
            "symbol":     "BTC-USD",
            "side":       "buy",
            "action":     "enter_long",
            "size_usd":   250.0,
            "confidence": 0.70,
            "regime":     "trending",
            "strategy":   "swing",
        }
        compiled, notes = self.compiler.compile_dict(d)
        self.assertIsNotNone(compiled)
        self.assertEqual(compiled.symbol, "BTC-USD")

    def test_compile_dict_missing_symbol_rejected(self):
        compiled, notes = self.compiler.compile_dict({
            "action":     "enter_long",
            "size_usd":   100.0,
            "confidence": 0.70,
            "regime":     "trending",
        })
        self.assertIsNone(compiled)

    def test_compile_dict_buy_action_mapping(self):
        d = {
            "symbol":     "ETH-USD",
            "action":     "buy",
            "size_usd":   50.0,
            "confidence": 0.70,
            "regime":     "trending",
            "strategy":   "swing",
        }
        compiled, notes = self.compiler.compile_dict(d)
        self.assertIsNotNone(compiled)
        self.assertEqual(compiled.side, "buy")

    def test_compile_dict_hold_no_confidence_floor(self):
        d = {
            "symbol":     "BTC-USD",
            "action":     "hold",
            "confidence": 0.0,
            "regime":     "unknown",
        }
        compiled, notes = self.compiler.compile_dict(d)
        self.assertIsNotNone(compiled)


# ---------------------------------------------------------------------------
# 8. Health / observability
# ---------------------------------------------------------------------------

class TestHealth(unittest.TestCase):

    def test_counters_incremented_on_accept(self):
        compiler = _fresh_compiler()
        compiler.compile(_valid_raw())
        compiler.compile(_valid_raw(symbol="ETH-USD"))
        health = compiler.get_health()
        self.assertEqual(health["total_compiled"], 2)
        self.assertEqual(health["accepted"], 2)
        self.assertEqual(health["rejected"], 0)

    def test_counters_incremented_on_reject(self):
        compiler = _fresh_compiler()
        compiler.compile(_valid_raw(symbol=""))
        compiler.compile(_valid_raw(confidence=2.0))
        health = compiler.get_health()
        self.assertEqual(health["rejected"], 2)

    def test_accept_rate_calculation(self):
        compiler = _fresh_compiler()
        compiler.compile(_valid_raw())
        compiler.compile(_valid_raw(symbol=""))  # reject
        health = compiler.get_health()
        self.assertAlmostEqual(health["accept_rate"], 0.5)

    def test_health_available_flag(self):
        compiler = _fresh_compiler()
        health = compiler.get_health()
        self.assertTrue(health["available"])


# ---------------------------------------------------------------------------
# 9. Singleton stability
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):

    def test_get_control_compiler_returns_same_instance(self):
        c1 = get_control_compiler()
        c2 = get_control_compiler()
        self.assertIs(c1, c2)

    def test_singleton_accepts_valid_signal(self):
        compiler = get_control_compiler()
        compiled, notes = compiler.compile(_valid_raw(symbol="DOT-USD"))
        self.assertIsNotNone(compiled)


if __name__ == "__main__":
    unittest.main()
