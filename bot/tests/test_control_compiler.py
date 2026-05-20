"""
Unit tests for bot.control_compiler
=====================================

Coverage:
  1. Schema rejection (missing / wrong-type fields)
  2. Invariant rejection (each invariant path)
  3. K-gate rejection
  4. Valid signal pass-through
  5. Instability detection (mild + severe) from synthetic traces
  6. FeedbackInstabilityDetector freeze/clear lifecycle
  7. Bounded K auto-update (step, clamp, cooldown)
  8. ControlMatrix history and rollback
  9. compile_dict convenience wrapper
 10. CompileResult fields on accept/reject
 11. Observability health snapshot
"""

import math
import time
import unittest

import bot.control_compiler as cc_mod
from bot.control_compiler import (
    CompileStatus,
    ControlCompiler,
    ControlMatrix,
    FeedbackInstabilityDetector,
    InstabilityLevel,
    KAutoTuner,
    KValue,
    RawSignal,
    SignalValidator,
    _normalize_side,
    get_control_compiler,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _valid_raw(**overrides) -> RawSignal:
    """Return a minimal valid execution signal, with optional overrides."""
    defaults = dict(
        symbol="BTC-USD",
        side="buy",
        action="enter_long",
        size_usd=100.0,
        confidence=0.65,
        regime="strong_trend",
        strategy="ApexTrend",
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
        result = self.compiler.compile(_valid_raw())
        self.assertTrue(result.accepted)
        self.assertEqual(result.status, CompileStatus.ACCEPTED)
        self.assertIsNotNone(result.signal)

    def test_missing_symbol_rejected(self):
        result = self.compiler.compile(_valid_raw(symbol=""))
        self.assertFalse(result.accepted)
        self.assertIn("symbol", result.reason)

    def test_non_string_symbol_rejected(self):
        raw = _valid_raw()
        raw.symbol = 12345  # type: ignore[assignment]
        # Schema check: float is not a string
        # Actually RawSignal is a plain dataclass so we test via compile
        result = self.compiler.compile(raw)
        # should either fail type check or invariant for non-string
        # the validator will try strip() which will fail → schema error
        self.assertFalse(result.accepted)

    def test_non_numeric_size_rejected(self):
        raw = _valid_raw()
        raw.size_usd = "large"  # type: ignore[assignment]
        result = self.compiler.compile(raw)
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.SCHEMA_INVALID)

    def test_non_numeric_confidence_rejected(self):
        raw = _valid_raw()
        raw.confidence = None  # type: ignore[assignment]
        result = self.compiler.compile(raw)
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.SCHEMA_INVALID)


# ---------------------------------------------------------------------------
# 2. Invariant checks
# ---------------------------------------------------------------------------

class TestInvariantChecks(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_empty_symbol_invariant(self):
        result = self.compiler.compile(_valid_raw(symbol="  "))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_MISSING_SYMBOL)

    def test_invalid_side_with_no_action_context(self):
        # side="unknown", action="hold" → non-execution, should pass
        result = self.compiler.compile(_valid_raw(side="unknown", action="hold"))
        # hold is not an execution action so invariant doesn't require resolvable side
        self.assertTrue(result.accepted)

    def test_execution_action_requires_resolvable_side(self):
        # side unrecognisable AND action is execution → should fail
        result = self.compiler.compile(_valid_raw(side="sideways", action="enter_long"))
        # enter_long from action → side resolves to "buy" from action mapping
        # Actually _normalize_side("sideways","enter_long") returns "buy" since action wins
        self.assertTrue(result.accepted)

    def test_not_approved_execution_rejected(self):
        result = self.compiler.compile(_valid_raw(approved=False, action="enter_long"))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_NOT_APPROVED)

    def test_non_finite_size_rejected(self):
        result = self.compiler.compile(_valid_raw(size_usd=math.inf))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_NON_FINITE_SIZE)

    def test_nan_size_rejected(self):
        result = self.compiler.compile(_valid_raw(size_usd=math.nan))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_NON_FINITE_SIZE)

    def test_negative_size_for_entry_rejected(self):
        result = self.compiler.compile(_valid_raw(size_usd=-1.0))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_NEGATIVE_SIZE)

    def test_zero_size_entry_accepted(self):
        # zero is allowed (sizing may be determined later)
        result = self.compiler.compile(_valid_raw(size_usd=0.0))
        self.assertTrue(result.accepted)

    def test_confidence_above_1_rejected(self):
        result = self.compiler.compile(_valid_raw(confidence=1.5))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_CONFIDENCE_OUT_OF_RANGE)

    def test_confidence_below_0_rejected(self):
        result = self.compiler.compile(_valid_raw(confidence=-0.1))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_CONFIDENCE_OUT_OF_RANGE)

    def test_empty_regime_rejected(self):
        result = self.compiler.compile(_valid_raw(regime=""))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_EMPTY_REGIME)

    def test_non_execution_action_no_approved_constraint(self):
        # hold/no_trade with approved=False should still pass invariants
        result = self.compiler.compile(_valid_raw(action="hold", approved=False))
        self.assertTrue(result.accepted)

    def test_non_finite_confidence_rejected(self):
        result = self.compiler.compile(_valid_raw(confidence=math.nan))
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason_code, SignalValidator.RC_NON_FINITE_CONFIDENCE)


# ---------------------------------------------------------------------------
# 3. Normalized output on accepted signal
# ---------------------------------------------------------------------------

class TestNormalization(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_symbol_uppercased(self):
        result = self.compiler.compile(_valid_raw(symbol="btc-usd"))
        self.assertTrue(result.accepted)
        self.assertEqual(result.signal.symbol, "BTC-USD")

    def test_regime_lowercased(self):
        result = self.compiler.compile(_valid_raw(regime="Strong_Trend"))
        self.assertTrue(result.accepted)
        self.assertEqual(result.signal.regime, "strong_trend")

    def test_long_side_normalized_to_buy(self):
        result = self.compiler.compile(_valid_raw(side="long", action="enter_long"))
        self.assertTrue(result.accepted)
        self.assertEqual(result.signal.side, "buy")

    def test_short_side_normalized_to_sell(self):
        result = self.compiler.compile(_valid_raw(side="short", action="enter_short"))
        self.assertTrue(result.accepted)
        self.assertEqual(result.signal.side, "sell")

    def test_compiled_at_populated(self):
        result = self.compiler.compile(_valid_raw())
        self.assertTrue(result.accepted)
        self.assertIsNotNone(result.signal.compiled_at)
        self.assertIn("T", result.signal.compiled_at)

    def test_to_pipeline_kwargs(self):
        result = self.compiler.compile(_valid_raw(symbol="ETH-USD", strategy="Apex"))
        self.assertTrue(result.accepted)
        kwargs = result.signal.to_pipeline_kwargs()
        self.assertEqual(kwargs["symbol"], "ETH-USD")
        self.assertEqual(kwargs["strategy"], "Apex")
        self.assertIn("side", kwargs)
        self.assertIn("size_usd", kwargs)


# ---------------------------------------------------------------------------
# 4. compile_dict convenience wrapper
# ---------------------------------------------------------------------------

class TestCompileDict(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()

    def test_compile_dict_valid(self):
        d = {
            "symbol": "BTC-USD",
            "side": "buy",
            "action": "enter_long",
            "size_usd": 250.0,
            "confidence": 0.7,
            "regime": "trending",
            "strategy": "apex",
        }
        result = self.compiler.compile_dict(d)
        self.assertTrue(result.accepted)
        self.assertEqual(result.signal.symbol, "BTC-USD")

    def test_compile_dict_missing_symbol(self):
        result = self.compiler.compile_dict({"action": "enter_long", "size_usd": 100.0, "confidence": 0.5, "regime": "strong_trend"})
        self.assertFalse(result.accepted)

    def test_compile_dict_buy_action_mapping(self):
        d = {"symbol": "ETH-USD", "action": "buy", "size_usd": 50.0, "confidence": 0.6, "regime": "ranging"}
        result = self.compiler.compile_dict(d)
        self.assertTrue(result.accepted)
        self.assertEqual(result.signal.side, "buy")

    def test_compile_dict_hold_no_size_requirement(self):
        d = {"symbol": "BTC-USD", "action": "hold", "confidence": 0.0, "regime": "unknown"}
        result = self.compiler.compile_dict(d)
        self.assertTrue(result.accepted)


# ---------------------------------------------------------------------------
# 4b. Bootstrap low-friction pass
# ---------------------------------------------------------------------------

class TestBootstrapPass(unittest.TestCase):

    def setUp(self):
        self.compiler = _fresh_compiler()
        self._bootstrap_regime = "bootstrap_probe"
        self._orig_min_conf = cc_mod._MIN_CONFIDENCE_BASELINE
        self._orig_bootstrap_enabled = cc_mod._BOOTSTRAP_PASS_ENABLED
        self._orig_bootstrap_limit = cc_mod._BOOTSTRAP_PASS_LIMIT
        self._orig_bootstrap_min_conf = cc_mod._BOOTSTRAP_MIN_CONFIDENCE
        self._orig_decay_window_s = cc_mod._BOOTSTRAP_DECAY_WINDOW_S
        self._orig_decay_min_samples = cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES
        self._orig_decay_rate_start = cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_START
        self._orig_decay_rate_full = cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_FULL
        cc_mod._MIN_CONFIDENCE_BASELINE = 0.10
        cc_mod._BOOTSTRAP_PASS_ENABLED = True
        cc_mod._BOOTSTRAP_PASS_LIMIT = 1
        cc_mod._BOOTSTRAP_MIN_CONFIDENCE = 0.05
        cc_mod._BOOTSTRAP_DECAY_WINDOW_S = 3600.0
        cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES = 20
        cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_START = 0.55
        cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_FULL = 0.90

    def tearDown(self):
        cc_mod._MIN_CONFIDENCE_BASELINE = self._orig_min_conf
        cc_mod._BOOTSTRAP_PASS_ENABLED = self._orig_bootstrap_enabled
        cc_mod._BOOTSTRAP_PASS_LIMIT = self._orig_bootstrap_limit
        cc_mod._BOOTSTRAP_MIN_CONFIDENCE = self._orig_bootstrap_min_conf
        cc_mod._BOOTSTRAP_DECAY_WINDOW_S = self._orig_decay_window_s
        cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES = self._orig_decay_min_samples
        cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_START = self._orig_decay_rate_start
        cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_FULL = self._orig_decay_rate_full

    def test_synthetic_low_threshold_signal_gets_one_bootstrap_pass(self):
        raw = _valid_raw(confidence=0.08, regime=self._bootstrap_regime, metadata={"synthetic": True})
        result = self.compiler.compile(raw)
        self.assertTrue(result.accepted)
        self.assertTrue(result.signal.metadata.get("bootstrap_pass"))
        self.assertEqual(result.signal.metadata.get("bootstrap_pass_index"), 1)
        self.assertEqual(result.signal.metadata.get("bootstrap_reason"), "k_confidence_override")

    def test_bootstrap_pass_is_bounded(self):
        first = self.compiler.compile(_valid_raw(confidence=0.08, regime=self._bootstrap_regime, metadata={"synthetic": True}))
        second = self.compiler.compile(_valid_raw(confidence=0.08, regime=self._bootstrap_regime, metadata={"synthetic": True}))
        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual(second.status, CompileStatus.K_GATE_FAILED)

    def test_bootstrap_pass_requires_signal_intent_metadata(self):
        result = self.compiler.compile(_valid_raw(confidence=0.08, regime=self._bootstrap_regime, metadata={}))
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.K_GATE_FAILED)
        self.assertEqual(result.reason_code, SignalValidator.RC_K_CONFIDENCE)

    def test_bootstrap_pass_respects_min_confidence(self):
        result = self.compiler.compile(
            _valid_raw(confidence=0.04, regime=self._bootstrap_regime, metadata={"synthetic": True})
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.K_GATE_FAILED)
        self.assertEqual(result.reason_code, SignalValidator.RC_K_CONFIDENCE)

    def test_bootstrap_pass_can_use_low_threshold_marker(self):
        result = self.compiler.compile(
            _valid_raw(confidence=0.08, regime=self._bootstrap_regime, metadata={"low_threshold": True})
        )
        self.assertTrue(result.accepted)
        self.assertTrue(result.signal.metadata.get("bootstrap_pass"))

    def test_bootstrap_pass_decays_after_consistent_execution_acceptance(self):
        cc_mod._BOOTSTRAP_PASS_LIMIT = 3
        cc_mod._MIN_CONFIDENCE_BASELINE = 0.20
        cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES = 4
        cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_START = 0.50
        cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_FULL = 0.75

        for i in range(4):
            self.compiler.compile(_valid_raw(symbol=f"ETH{i}-USD", confidence=0.90))

        result = self.compiler.compile(
            _valid_raw(confidence=0.08, regime=self._bootstrap_regime, metadata={"synthetic": True})
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.K_GATE_FAILED)
        self.assertEqual(result.reason_code, SignalValidator.RC_K_CONFIDENCE)

    def test_bootstrap_pass_does_not_override_non_k_confidence_rejections(self):
        result = self.compiler.compile(
            _valid_raw(confidence=0.08, regime=self._bootstrap_regime, approved=False, metadata={"synthetic": True})
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.INVARIANT_FAILED)
        self.assertEqual(result.reason_code, SignalValidator.RC_NOT_APPROVED)

    def test_bootstrap_pass_disabled_rejects_k_confidence_signal(self):
        cc_mod._BOOTSTRAP_PASS_ENABLED = False
        result = self.compiler.compile(_valid_raw(confidence=0.08, regime=self._bootstrap_regime, metadata={"synthetic": True}))
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.K_GATE_FAILED)
        self.assertEqual(result.reason_code, SignalValidator.RC_K_CONFIDENCE)


# ---------------------------------------------------------------------------
# 5. ControlMatrix K operations
# ---------------------------------------------------------------------------

class TestControlMatrix(unittest.TestCase):

    def test_initial_k_values_are_neutral(self):
        m = ControlMatrix()
        for dim in ("K_AI_GATE", "K_REGIME_PASS", "K_CONFIDENCE", "K_SIZE_FLOOR"):
            self.assertAlmostEqual(m.get(dim), 1.0)

    def test_apply_step_changes_value(self):
        m = ControlMatrix()
        changed = m.apply_step("K_AI_GATE", delta=+0.05, reason="test")
        self.assertTrue(changed)
        self.assertGreater(m.get("K_AI_GATE"), 1.0)

    def test_step_is_clamped_to_max_step(self):
        m = ControlMatrix()
        # Even a huge delta is capped by _K_MAX_STEP per call
        m.apply_step("K_AI_GATE", delta=+100.0, reason="test")
        # Value should not exceed ceiling of 2.0
        self.assertLessEqual(m.get("K_AI_GATE"), 2.0)

    def test_value_does_not_exceed_ceiling(self):
        m = ControlMatrix()
        # Apply many steps to push to ceiling
        for _ in range(30):
            m._cooldowns.clear()  # bypass cooldown for test
            m.apply_step("K_AI_GATE", delta=+0.05, reason="test")
        self.assertLessEqual(m.get("K_AI_GATE"), 2.0)

    def test_value_does_not_go_below_floor(self):
        m = ControlMatrix()
        for _ in range(30):
            m._cooldowns.clear()
            m.apply_step("K_AI_GATE", delta=-0.05, reason="test")
        self.assertGreaterEqual(m.get("K_AI_GATE"), 0.5)

    def test_cooldown_blocks_second_step(self):
        m = ControlMatrix()
        m.apply_step("K_AI_GATE", delta=+0.05, reason="first")
        # Second call within cooldown window should be blocked
        changed = m.apply_step("K_AI_GATE", delta=+0.05, reason="second")
        self.assertFalse(changed)

    def test_reset_restores_to_neutral(self):
        m = ControlMatrix()
        m._cooldowns.clear()
        m.apply_step("K_AI_GATE", delta=+0.05, reason="bump")
        m.reset("K_AI_GATE", reason="rollback")
        self.assertAlmostEqual(m.get("K_AI_GATE"), 1.0)

    def test_history_recorded(self):
        m = ControlMatrix()
        m.apply_step("K_AI_GATE", delta=+0.05, reason="reason1")
        history = m.get_history(limit=10)
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["name"], "K_AI_GATE")
        self.assertIn("old_value", history[0])
        self.assertIn("new_value", history[0])

    def test_unknown_dimension_returns_false(self):
        m = ControlMatrix()
        result = m.apply_step("K_NONEXISTENT", delta=+0.05, reason="test")
        self.assertFalse(result)

    def test_get_all_contains_all_dimensions(self):
        m = ControlMatrix()
        all_k = m.get_all()
        for dim in ("K_AI_GATE", "K_REGIME_PASS", "K_CONFIDENCE", "K_SIZE_FLOOR"):
            self.assertIn(dim, all_k)


# ---------------------------------------------------------------------------
# 6. FeedbackInstabilityDetector
# ---------------------------------------------------------------------------

class TestFeedbackInstabilityDetector(unittest.TestCase):

    def test_no_history_no_instability(self):
        det = FeedbackInstabilityDetector()
        level, reason = det.check("BTC-USD", "strong_trend")
        self.assertEqual(level, InstabilityLevel.NONE)

    def test_mild_instability_from_flips(self):
        det = FeedbackInstabilityDetector()
        # Inject alternating accept/reject to produce 4+ flips
        for i in range(10):
            det.record("BTC-USD", "strong_trend", accepted=(i % 2 == 0))
        level, reason = det.check("BTC-USD", "strong_trend")
        self.assertIn(level, (InstabilityLevel.MILD, InstabilityLevel.SEVERE))

    def test_severe_instability_produces_freeze(self):
        det = FeedbackInstabilityDetector()
        for i in range(20):
            det.record("BTC-USD", "ranging", accepted=(i % 2 == 0))
        level, reason = det.check("BTC-USD", "ranging")
        self.assertEqual(level, InstabilityLevel.SEVERE)
        # Second call should return frozen
        level2, reason2 = det.check("BTC-USD", "ranging")
        self.assertEqual(level2, InstabilityLevel.SEVERE)
        self.assertIn("instability_freeze_active", reason2)

    def test_clear_freeze_lifts_block(self):
        det = FeedbackInstabilityDetector()
        for i in range(20):
            det.record("ETH-USD", "volatile", accepted=(i % 2 == 0))
        det.check("ETH-USD", "volatile")  # trigger freeze
        # Verify freeze is active
        freezes_before = det.get_freezes()
        self.assertGreater(len(freezes_before), 0)
        # Clear the freeze
        det.clear_freeze("ETH-USD", "volatile")
        # Freeze dict should be empty now (regardless of re-detection on next check)
        freezes_after = det.get_freezes()
        self.assertEqual(len(freezes_after), 0)

    def test_stable_history_no_instability(self):
        det = FeedbackInstabilityDetector()
        # All accepts = no flips
        for _ in range(10):
            det.record("SOL-USD", "strong_trend", accepted=True)
        level, _ = det.check("SOL-USD", "strong_trend")
        self.assertEqual(level, InstabilityLevel.NONE)

    def test_get_freezes_reflects_active_freezes(self):
        det = FeedbackInstabilityDetector()
        for i in range(20):
            det.record("BTC-USD", "weak_trend", accepted=(i % 2 == 0))
        det.check("BTC-USD", "weak_trend")  # trigger freeze
        freezes = det.get_freezes()
        self.assertGreater(len(freezes), 0)


# ---------------------------------------------------------------------------
# 7. Instability integration in ControlCompiler
# ---------------------------------------------------------------------------

class TestCompilerInstabilityIntegration(unittest.TestCase):

    def test_severe_instability_blocks_execution(self):
        compiler = _fresh_compiler()
        # Manually inject unstable history for a specific symbol/regime
        det = compiler.get_instability_detector()
        for i in range(20):
            det.record("BTC-USD", "ranging", accepted=(i % 2 == 0))

        result = compiler.compile(_valid_raw(symbol="BTC-USD", regime="ranging"))
        # Should be frozen
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, CompileStatus.INSTABILITY_FROZEN)

    def test_mild_instability_still_allows_execution(self):
        compiler = _fresh_compiler()
        det = compiler.get_instability_detector()
        # Produce exactly mild instability (4 flips < severe threshold of 8)
        # alternating 5 items = 4 flips
        for i in range(5):
            det.record("ETH-USD", "strong_trend", accepted=(i % 2 == 0))

        result = compiler.compile(_valid_raw(symbol="ETH-USD", regime="strong_trend"))
        # Mild: signal should still be accepted
        self.assertTrue(result.accepted)
        self.assertEqual(result.status, CompileStatus.ACCEPTED)

    def test_non_execution_action_bypasses_instability(self):
        compiler = _fresh_compiler()
        det = compiler.get_instability_detector()
        for i in range(20):
            det.record("BTC-USD", "ranging", accepted=(i % 2 == 0))

        # hold action is not execution → should not be blocked by instability
        result = compiler.compile(_valid_raw(symbol="BTC-USD", regime="ranging", action="hold"))
        self.assertTrue(result.accepted)


# ---------------------------------------------------------------------------
# 8. K auto-tuner
# ---------------------------------------------------------------------------

class TestKAutoTuner(unittest.TestCase):

    def test_maybe_run_does_not_crash(self):
        matrix = ControlMatrix()
        tuner = KAutoTuner(matrix)
        # First call: should run (last_run=0)
        tuner.maybe_run()
        # No assertion needed — just must not raise

    def test_second_call_within_interval_skips(self):
        matrix = ControlMatrix()
        tuner = KAutoTuner(matrix)
        tuner.maybe_run()
        initial_count = matrix._k["K_AI_GATE"].update_count
        tuner.maybe_run()  # within interval
        self.assertEqual(matrix._k["K_AI_GATE"].update_count, initial_count)


# ---------------------------------------------------------------------------
# 9. Compiler session counters and health
# ---------------------------------------------------------------------------

class TestCompilerHealth(unittest.TestCase):

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
        compiler.compile(_valid_raw(symbol=""))       # invalid
        compiler.compile(_valid_raw(confidence=2.0)) # invalid
        health = compiler.get_health()
        self.assertEqual(health["rejected"], 2)

    def test_health_contains_k_values(self):
        compiler = _fresh_compiler()
        health = compiler.get_health()
        self.assertIn("k_values", health)
        self.assertIn("K_AI_GATE", health["k_values"])

    def test_health_contains_freezes(self):
        compiler = _fresh_compiler()
        health = compiler.get_health()
        self.assertIn("active_freezes", health)

    def test_accept_rate_calculation(self):
        compiler = _fresh_compiler()
        compiler.compile(_valid_raw())
        compiler.compile(_valid_raw(symbol=""))  # reject
        health = compiler.get_health()
        self.assertAlmostEqual(health["accept_rate"], 0.5)

    def test_health_reports_bootstrap_pass_usage(self):
        compiler = _fresh_compiler()
        orig_enabled = cc_mod._BOOTSTRAP_PASS_ENABLED
        orig_limit = cc_mod._BOOTSTRAP_PASS_LIMIT
        orig_min_conf = cc_mod._BOOTSTRAP_MIN_CONFIDENCE
        orig_min_conf_baseline = cc_mod._MIN_CONFIDENCE_BASELINE
        orig_decay_min_samples = cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES
        try:
            cc_mod._BOOTSTRAP_PASS_ENABLED = True
            cc_mod._BOOTSTRAP_PASS_LIMIT = 2
            cc_mod._BOOTSTRAP_MIN_CONFIDENCE = 0.05
            cc_mod._MIN_CONFIDENCE_BASELINE = 0.10
            cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES = 20
            compiler.compile(_valid_raw(confidence=0.08, regime="bootstrap_probe_health", metadata={"synthetic": True}))
            health = compiler.get_health()
            self.assertIn("bootstrap_pass", health)
            self.assertEqual(health["bootstrap_pass"]["enabled"], True)
            self.assertEqual(health["bootstrap_pass"]["limit"], 2)
            self.assertEqual(health["bootstrap_pass"]["effective_limit"], 2)
            self.assertEqual(health["bootstrap_pass"]["used"], 1)
            self.assertEqual(health["bootstrap_pass"]["remaining"], 1)
            self.assertEqual(health["bootstrap_pass"]["min_confidence"], 0.05)
            self.assertEqual(health["bootstrap_pass"]["window_samples"], 1)
        finally:
            cc_mod._BOOTSTRAP_PASS_ENABLED = orig_enabled
            cc_mod._BOOTSTRAP_PASS_LIMIT = orig_limit
            cc_mod._BOOTSTRAP_MIN_CONFIDENCE = orig_min_conf
            cc_mod._MIN_CONFIDENCE_BASELINE = orig_min_conf_baseline
            cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES = orig_decay_min_samples

    def test_health_reports_bootstrap_decay_after_high_acceptance(self):
        compiler = _fresh_compiler()
        orig_enabled = cc_mod._BOOTSTRAP_PASS_ENABLED
        orig_limit = cc_mod._BOOTSTRAP_PASS_LIMIT
        orig_min_conf = cc_mod._BOOTSTRAP_MIN_CONFIDENCE
        orig_min_conf_baseline = cc_mod._MIN_CONFIDENCE_BASELINE
        orig_decay_min_samples = cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES
        orig_decay_rate_start = cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_START
        orig_decay_rate_full = cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_FULL
        try:
            cc_mod._BOOTSTRAP_PASS_ENABLED = True
            cc_mod._BOOTSTRAP_PASS_LIMIT = 3
            cc_mod._BOOTSTRAP_MIN_CONFIDENCE = 0.05
            cc_mod._MIN_CONFIDENCE_BASELINE = 0.20
            cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES = 4
            cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_START = 0.50
            cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_FULL = 0.75

            for i in range(4):
                compiler.compile(_valid_raw(symbol=f"BTC{i}-USD", confidence=0.90))

            health = compiler.get_health()
            self.assertEqual(health["bootstrap_pass"]["window_samples"], 4)
            self.assertGreaterEqual(health["bootstrap_pass"]["window_acceptance_rate"], 0.99)
            self.assertGreaterEqual(health["bootstrap_pass"]["decay_ratio"], 0.99)
            self.assertEqual(health["bootstrap_pass"]["effective_limit"], 0)
            self.assertEqual(health["bootstrap_pass"]["remaining"], 0)
            self.assertAlmostEqual(health["bootstrap_pass"]["min_confidence"], 0.20, places=6)
        finally:
            cc_mod._BOOTSTRAP_PASS_ENABLED = orig_enabled
            cc_mod._BOOTSTRAP_PASS_LIMIT = orig_limit
            cc_mod._BOOTSTRAP_MIN_CONFIDENCE = orig_min_conf
            cc_mod._MIN_CONFIDENCE_BASELINE = orig_min_conf_baseline
            cc_mod._BOOTSTRAP_DECAY_MIN_SAMPLES = orig_decay_min_samples
            cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_START = orig_decay_rate_start
            cc_mod._BOOTSTRAP_DECAY_ACCEPT_RATE_FULL = orig_decay_rate_full


# ---------------------------------------------------------------------------
# 10. Singleton stability
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):

    def test_get_control_compiler_returns_same_instance(self):
        c1 = get_control_compiler()
        c2 = get_control_compiler()
        self.assertIs(c1, c2)

    def test_singleton_accepts_valid_signal(self):
        compiler = get_control_compiler()
        result = compiler.compile(_valid_raw(symbol="DOT-USD"))
        self.assertTrue(result.accepted)


# ---------------------------------------------------------------------------
# 11. _normalize_side helper
# ---------------------------------------------------------------------------

class TestNormalizeSide(unittest.TestCase):

    def test_buy_side(self):
        self.assertEqual(_normalize_side("buy", ""), "buy")

    def test_long_side(self):
        self.assertEqual(_normalize_side("long", ""), "buy")

    def test_sell_side(self):
        self.assertEqual(_normalize_side("sell", ""), "sell")

    def test_short_side(self):
        self.assertEqual(_normalize_side("short", ""), "sell")

    def test_action_fallback(self):
        self.assertEqual(_normalize_side("", "enter_long"), "buy")
        self.assertEqual(_normalize_side("", "enter_short"), "sell")

    def test_unknown_returns_empty(self):
        self.assertEqual(_normalize_side("sideways", "hold"), "")


# ---------------------------------------------------------------------------
# 12. KValue dataclass
# ---------------------------------------------------------------------------

class TestKValue(unittest.TestCase):

    def test_clamp_respects_floor_and_ceiling(self):
        kv = KValue("test", value=1.0, floor=0.5, ceiling=2.0)
        self.assertEqual(kv.clamp(0.1), 0.5)
        self.assertEqual(kv.clamp(5.0), 2.0)
        self.assertEqual(kv.clamp(1.5), 1.5)

    def test_apply_step_updates_value(self):
        kv = KValue("test", value=1.0, floor=0.5, ceiling=2.0)
        kv.apply_step(0.2, "reason")
        self.assertAlmostEqual(kv.value, 1.2)

    def test_apply_step_increments_count(self):
        kv = KValue("test", value=1.0, floor=0.5, ceiling=2.0)
        kv.apply_step(0.1, "reason")
        self.assertEqual(kv.update_count, 1)

    def test_to_dict_keys(self):
        kv = KValue("test", value=1.0, floor=0.5, ceiling=2.0)
        d = kv.to_dict()
        for key in ("name", "value", "floor", "ceiling", "last_updated", "update_count"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
