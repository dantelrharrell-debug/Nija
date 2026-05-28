"""
Tests for the stateful, attempt-scoped DeterministicEntryValidator (v2).

Covers:
- AttemptKey contract enforcement
- reduce() idempotency: same key → same AttemptRecord
- reduce() independence: different attempt_n → independent records
- emit_once() idempotency: emits once, no-op on repeat
- should_retry() honours RejectionClass + spec
- ExecutionContractSpec.allows_retry max_retries ceiling
- Backward-compatible validate_entry() still returns ValidationResult
- PipelineRequest now carries attempt_n field
"""

from __future__ import annotations

import threading
import unittest
from datetime import datetime

from bot.deterministic_entry_validator import (
    AttemptKey,
    AttemptRecord,
    DeterministicEntryValidator,
    EmissionState,
    ExecutionContractSpec,
    RejectionClass,
    RejectionCode,
    ValidationContext,
    ValidationResult,
    get_entry_validator,
)
from bot.pipeline_request_contract import PipelineRequest


def _passing_context(**overrides) -> ValidationContext:
    defaults = dict(
        balance=100.0,
        tier_name="SAVER",
        current_position_count=0,
        open_positions=[],
        available_capital=90.0,
        symbol="BTC-USD",
        signal_type="LONG",
        signal_quality=75.0,
        signal_confidence=0.70,
        proposed_size_usd=40.0,
        exchange_name="coinbase",
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


def _failing_context(**overrides) -> ValidationContext:
    return _passing_context(balance=10.0, **overrides)  # balance < min → BALANCE_TOO_LOW


class TestAttemptKey(unittest.TestCase):
    def test_basic_construction(self):
        k = AttemptKey(intent_id="abc", attempt_n=0)
        self.assertEqual(k.intent_id, "abc")
        self.assertEqual(k.attempt_n, 0)

    def test_next_increments(self):
        k = AttemptKey(intent_id="x", attempt_n=2)
        self.assertEqual(k.next(), AttemptKey(intent_id="x", attempt_n=3))

    def test_negative_attempt_n_raises(self):
        with self.assertRaises(ValueError):
            AttemptKey(intent_id="x", attempt_n=-1)

    def test_hashable_for_dict(self):
        d = {AttemptKey("a", 0): "v1", AttemptKey("a", 1): "v2"}
        self.assertEqual(d[AttemptKey("a", 0)], "v1")
        self.assertEqual(d[AttemptKey("a", 1)], "v2")


class TestExecutionContractSpec(unittest.TestCase):
    def test_allows_retry_transient(self):
        spec = ExecutionContractSpec()
        self.assertTrue(spec.allows_retry(RejectionClass.TRANSIENT, attempt_n=0))

    def test_refuses_retry_permanent(self):
        spec = ExecutionContractSpec()
        self.assertFalse(spec.allows_retry(RejectionClass.PERMANENT, attempt_n=0))

    def test_refuses_retry_authority_blocked_by_default(self):
        spec = ExecutionContractSpec()
        self.assertFalse(spec.allows_retry(RejectionClass.AUTHORITY_BLOCKED, attempt_n=0))

    def test_max_retries_ceiling(self):
        spec = ExecutionContractSpec(max_retries=2)
        self.assertTrue(spec.allows_retry(RejectionClass.TRANSIENT, attempt_n=1))
        self.assertFalse(spec.allows_retry(RejectionClass.TRANSIENT, attempt_n=2))

    def test_enforce_requires_intent_id(self):
        spec = ExecutionContractSpec(intent_id_required=True)
        with self.assertRaises(ValueError):
            spec.enforce(AttemptKey(intent_id="", attempt_n=0))

    def test_enforce_passes_valid_key(self):
        spec = ExecutionContractSpec()
        spec.enforce(AttemptKey(intent_id="intent-001", attempt_n=0))  # no exception


class TestReducerIdempotency(unittest.TestCase):
    def setUp(self):
        spec = ExecutionContractSpec(intent_id_required=False)
        self.validator = DeterministicEntryValidator(spec=spec)

    def test_same_key_returns_same_record(self):
        key = AttemptKey(intent_id="intent-001", attempt_n=0)
        ctx = _passing_context()
        r1 = self.validator.reduce(key, ctx)
        r2 = self.validator.reduce(key, ctx)
        self.assertIs(r1, r2)

    def test_same_key_different_context_returns_stored_record(self):
        """Changing context after first reduce must NOT change the stored outcome."""
        key = AttemptKey(intent_id="intent-002", attempt_n=0)
        ctx_pass = _passing_context()
        ctx_fail = _failing_context()
        r1 = self.validator.reduce(key, ctx_pass)
        self.assertTrue(r1.passed)
        # Second call with a failing context must still return the stored passing record
        r2 = self.validator.reduce(key, ctx_fail)
        self.assertTrue(r2.passed)
        self.assertIs(r1, r2)

    def test_different_attempt_n_independent_records(self):
        key0 = AttemptKey(intent_id="intent-003", attempt_n=0)
        key1 = AttemptKey(intent_id="intent-003", attempt_n=1)
        ctx = _passing_context()
        r0 = self.validator.reduce(key0, ctx)
        r1 = self.validator.reduce(key1, ctx)
        self.assertIsNot(r0, r1)
        self.assertEqual(r0.key.attempt_n, 0)
        self.assertEqual(r1.key.attempt_n, 1)

    def test_concurrent_reduce_same_key(self):
        """Multiple threads racing on the same key must all get the same record."""
        key = AttemptKey(intent_id="intent-conc", attempt_n=0)
        ctx = _passing_context()
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(self.validator.reduce(key, ctx))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads must have received the same object
        self.assertEqual(len(results), 8)
        first = results[0]
        for r in results[1:]:
            self.assertIs(r, first)

    def test_contract_enforced_empty_intent_id(self):
        spec = ExecutionContractSpec(intent_id_required=True)
        v = DeterministicEntryValidator(spec=spec)
        key = AttemptKey(intent_id="", attempt_n=0)
        with self.assertRaises(ValueError):
            v.reduce(key, _passing_context())


class TestEmitOnce(unittest.TestCase):
    def setUp(self):
        spec = ExecutionContractSpec(intent_id_required=False, idempotent_emission=True)
        self.validator = DeterministicEntryValidator(spec=spec)

    def test_emit_once_returns_true_first_call(self):
        key = AttemptKey(intent_id="emit-001", attempt_n=0)
        record = self.validator.reduce(key, _passing_context())
        emitted = self.validator.emit_once(record)
        self.assertTrue(emitted)

    def test_emit_once_returns_false_second_call(self):
        key = AttemptKey(intent_id="emit-002", attempt_n=0)
        record = self.validator.reduce(key, _passing_context())
        self.validator.emit_once(record)
        emitted2 = self.validator.emit_once(record)
        self.assertFalse(emitted2)

    def test_emit_marks_stored_record_emitted(self):
        key = AttemptKey(intent_id="emit-003", attempt_n=0)
        record = self.validator.reduce(key, _passing_context())
        self.assertEqual(record.emission_state, EmissionState.PENDING)
        self.validator.emit_once(record)
        stored = self.validator._records[key]
        self.assertEqual(stored.emission_state, EmissionState.EMITTED)

    def test_emit_once_disabled_by_spec(self):
        spec = ExecutionContractSpec(idempotent_emission=False, intent_id_required=False)
        v = DeterministicEntryValidator(spec=spec)
        key = AttemptKey(intent_id="emit-004", attempt_n=0)
        record = v.reduce(key, _passing_context())
        emitted = v.emit_once(record)
        self.assertFalse(emitted)


class TestShouldRetry(unittest.TestCase):
    def _validator(self, **spec_kwargs):
        spec = ExecutionContractSpec(intent_id_required=False, **spec_kwargs)
        return DeterministicEntryValidator(spec=spec)

    def test_no_retry_on_passed(self):
        v = self._validator()
        key = AttemptKey("r1", 0)
        record = v.reduce(key, _passing_context())
        self.assertTrue(record.passed)
        self.assertFalse(v.should_retry(record))

    def test_retry_on_transient(self):
        v = self._validator()
        key = AttemptKey("r2", 0)
        # COOLDOWN_ACTIVE → TRANSIENT
        ctx = _passing_context(balance=100.0)
        from datetime import datetime, timedelta
        ctx2 = ValidationContext(
            balance=100.0,
            tier_name="SAVER",
            current_position_count=0,
            open_positions=[],
            available_capital=90.0,
            symbol="BTC-USD",
            signal_type="LONG",
            signal_quality=75.0,
            signal_confidence=0.70,
            proposed_size_usd=40.0,
            exchange_name="coinbase",
            cooldown_until=datetime.now() + timedelta(hours=1),
        )
        record = v.reduce(key, ctx2)
        self.assertFalse(record.passed)
        self.assertEqual(record.rejection_class, RejectionClass.TRANSIENT)
        self.assertTrue(v.should_retry(record))

    def test_no_retry_on_permanent(self):
        v = self._validator()
        key = AttemptKey("r3", 0)
        # BALANCE_TOO_LOW → PERMANENT
        record = v.reduce(key, _failing_context())
        self.assertFalse(record.passed)
        self.assertEqual(record.rejection_class, RejectionClass.PERMANENT)
        self.assertFalse(v.should_retry(record))

    def test_no_retry_on_authority_blocked_by_default(self):
        v = self._validator()
        key = AttemptKey("r4", 0)
        # DRAWDOWN_HALT → AUTHORITY_BLOCKED
        ctx = _passing_context(in_drawdown_halt=True)
        record = v.reduce(key, ctx)
        self.assertFalse(record.passed)
        self.assertEqual(record.rejection_class, RejectionClass.AUTHORITY_BLOCKED)
        self.assertFalse(v.should_retry(record))

    def test_max_retries_ceiling_blocks_transient(self):
        v = self._validator(max_retries=1)
        from datetime import datetime, timedelta
        ctx = ValidationContext(
            balance=100.0,
            tier_name="SAVER",
            current_position_count=0,
            open_positions=[],
            available_capital=90.0,
            symbol="BTC-USD",
            signal_type="LONG",
            signal_quality=75.0,
            signal_confidence=0.70,
            proposed_size_usd=40.0,
            exchange_name="coinbase",
            cooldown_until=datetime.now() + timedelta(hours=1),
        )
        # attempt_n=0 → below max_retries=1 → retry allowed
        key0 = AttemptKey("r5", 0)
        rec0 = v.reduce(key0, ctx)
        self.assertTrue(v.should_retry(rec0))
        # attempt_n=1 → at max_retries=1 → no retry
        key1 = AttemptKey("r5", 1)
        rec1 = v.reduce(key1, ctx)
        self.assertFalse(v.should_retry(rec1))


class TestBackwardCompat(unittest.TestCase):
    """validate_entry() must still behave like the original v1 API."""

    def setUp(self):
        self.validator = DeterministicEntryValidator()

    def test_returns_validation_result(self):
        result = self.validator.validate_entry(_passing_context())
        self.assertIsInstance(result, ValidationResult)

    def test_each_call_independent(self):
        """Unlike reduce(), two validate_entry calls are never deduplicated."""
        ctx = _passing_context()
        r1 = self.validator.validate_entry(ctx)
        r2 = self.validator.validate_entry(ctx)
        # Both should pass and be equal in content, but not the same object
        self.assertTrue(r1.passed)
        self.assertTrue(r2.passed)
        self.assertIsNot(r1, r2)

    def test_history_populated(self):
        before = len(self.validator.validation_history)
        self.validator.validate_entry(_passing_context())
        self.assertEqual(len(self.validator.validation_history), before + 1)

    def test_does_not_pollute_reducer_store(self):
        """validate_entry should not add entries to _records."""
        before = len(self.validator._records)
        self.validator.validate_entry(_passing_context())
        self.assertEqual(len(self.validator._records), before)


class TestGetValidationStats(unittest.TestCase):
    def test_stats_include_reducer_and_history(self):
        spec = ExecutionContractSpec(intent_id_required=False)
        v = DeterministicEntryValidator(spec=spec)
        # Legacy path
        v.validate_entry(_passing_context())
        # Reducer path
        v.reduce(AttemptKey("s1", 0), _passing_context())
        stats = v.get_validation_stats()
        self.assertEqual(stats["total"], 2)
        self.assertIn("reducer_attempts", stats)
        self.assertIn("emitted", stats)


class TestPipelineRequestAttemptN(unittest.TestCase):
    def test_default_attempt_n_zero(self):
        req = PipelineRequest(symbol="BTC-USD", side="buy", size_usd=50.0, strategy="apex")
        self.assertEqual(req.attempt_n, 0)

    def test_explicit_attempt_n(self):
        req = PipelineRequest(symbol="BTC-USD", side="buy", size_usd=50.0, strategy="apex", attempt_n=2)
        self.assertEqual(req.attempt_n, 2)


if __name__ == "__main__":
    unittest.main()
