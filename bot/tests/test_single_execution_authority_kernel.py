"""
Tests for the Single Execution Authority Kernel (SEAK).
"""

from __future__ import annotations

import threading
import time
import unittest
import uuid as _uuid
from unittest.mock import MagicMock, patch

# Timing tolerance for issued_at assertions (seconds).
_TIMING_TOLERANCE_S: float = 0.01
# Generous upper-bound for token TTL in tests (intentionally larger than the
# default _SLOT_TIMEOUT_S = 30 s to guard against misconfigured overrides).
_MAX_TTL_S: float = 120.0

# Reset the singleton before every test to guarantee isolation.
import bot.single_execution_authority_kernel as seak_mod
from bot.single_execution_authority_kernel import (
    AuditOutcome,
    ExecutionRequest,
    RejectionReason,
    SingleExecutionAuthorityKernel,
    get_seak,
)


def _fresh_seak() -> SingleExecutionAuthorityKernel:
    """Return a brand-new kernel instance (not the singleton).

    The external TradeDuplicationGuard and ExecutionLayerHardening are
    disabled here so that tests are fully isolated from those singletons.
    """
    s = SingleExecutionAuthorityKernel()
    # Disable the external dedup guard — each test creates a fresh SEAK but
    # the TradeDuplicationGuard singleton persists across tests, which would
    # cause cross-test contamination.
    s._dedup_guard = None
    s._dedup_guard_loaded = True
    # Disable external hardening so tests don't depend on its singleton state.
    s._hardening = None
    s._hardening_loaded = True
    # Disable the health monitor so tests run without its lazy-loaded state.
    s._health_monitor = None
    s._health_loaded = True
    return s


class TestAcquireBasic(unittest.TestCase):
    """Happy-path acquire / release."""

    def setUp(self):
        self.seak = _fresh_seak()

    def test_acquire_granted(self):
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0, caller="test")
        self.assertTrue(token.granted)
        self.assertEqual(token.symbol, "BTC-USD")
        self.seak.release(token)

    def test_release_frees_slot(self):
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        self.seak.release(token)
        # Should be grantable again after release.
        token2 = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=200.0)
        self.assertTrue(token2.granted)
        self.seak.release(token2)

    def test_symbol_is_uppercased(self):
        token = self.seak.acquire(symbol="eth-usd", side="buy", size_usd=50.0)
        self.assertEqual(token.symbol, "ETH-USD")
        self.seak.release(token)

    def test_side_stored_lowercase(self):
        token = self.seak.acquire(symbol="SOL-USD", side="BUY", size_usd=50.0)
        self.assertEqual(token.side, "buy")
        self.seak.release(token)

    def test_denied_token_release_is_noop(self):
        # Releasing a denied token must not raise.
        self.seak.emergency_halt("test")
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertFalse(token.granted)
        self.seak.release(token)  # Must not raise.
        self.seak.resume()


class TestInvalidRequests(unittest.TestCase):
    def setUp(self):
        self.seak = _fresh_seak()

    def test_empty_symbol_rejected(self):
        token = self.seak.acquire(symbol="", side="buy", size_usd=100.0)
        self.assertFalse(token.granted)
        self.assertEqual(token.rejection_reason, RejectionReason.INVALID_REQUEST)

    def test_zero_size_rejected(self):
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=0.0)
        self.assertFalse(token.granted)
        self.assertEqual(token.rejection_reason, RejectionReason.INVALID_REQUEST)

    def test_negative_size_rejected(self):
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=-50.0)
        self.assertFalse(token.granted)
        self.assertEqual(token.rejection_reason, RejectionReason.INVALID_REQUEST)


class TestMutualExclusion(unittest.TestCase):
    """Per-symbol lock prevents concurrent orders."""

    def setUp(self):
        self.seak = _fresh_seak()

    def test_same_symbol_blocked_while_held(self):
        token1 = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0, timeout=0.1)
        self.assertTrue(token1.granted)

        # Second acquire on same symbol must time out.
        token2 = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0, timeout=0.05)
        self.assertFalse(token2.granted)
        self.assertEqual(token2.rejection_reason, RejectionReason.SLOT_BUSY)

        self.seak.release(token1)

    def test_different_symbols_independent(self):
        token_btc = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        token_eth = self.seak.acquire(symbol="ETH-USD", side="buy", size_usd=100.0)
        self.assertTrue(token_btc.granted)
        self.assertTrue(token_eth.granted)
        self.seak.release(token_btc)
        self.seak.release(token_eth)

    def test_slot_reusable_after_release(self):
        for _ in range(3):
            token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0, timeout=0.1)
            self.assertTrue(token.granted)
            self.seak.release(token)

    def test_concurrent_threads_serialised(self):
        """Only one thread should hold the slot at any point."""
        concurrent_holders: list[int] = []
        errors: list[str] = []

        def worker(tid: int):
            token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=10.0, timeout=2.0)
            if not token.granted:
                return
            concurrent_holders.append(tid)
            if len(concurrent_holders) > 1:
                errors.append(f"Concurrent holders: {concurrent_holders}")
            time.sleep(0.02)
            concurrent_holders.remove(tid)
            self.seak.release(token)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Mutual exclusion violated: {errors}")


class TestEmergencyHalt(unittest.TestCase):
    def setUp(self):
        self.seak = _fresh_seak()

    def test_halt_blocks_new_acquisitions(self):
        self.seak.emergency_halt("unit test halt")
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertFalse(token.granted)
        self.assertEqual(token.rejection_reason, RejectionReason.EMERGENCY_HALT)

    def test_resume_unblocks(self):
        self.seak.emergency_halt("test")
        self.seak.resume()
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        self.seak.release(token)

    def test_is_halted_property(self):
        self.assertFalse(self.seak.is_halted)
        self.seak.emergency_halt("check")
        self.assertTrue(self.seak.is_halted)
        self.seak.resume()
        self.assertFalse(self.seak.is_halted)

    def test_force_release_all(self):
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        released = self.seak.force_release_all("test")
        self.assertGreaterEqual(released, 1)
        # Slot should be free now.
        token2 = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token2.granted)
        self.seak.release(token2)


class TestDuplication(unittest.TestCase):
    """Duplicate fingerprint suppression while a slot is in-flight."""

    def setUp(self):
        self.seak = _fresh_seak()

    def test_duplicate_while_slot_held_blocked(self):
        """A second acquire with the same fingerprint while the first is still
        in-flight must be rejected — the slot is held so it gets SLOT_BUSY,
        not DUPLICATE_REQUEST (dedup fires after the lock is acquired)."""
        token1 = self.seak.acquire(
            symbol="BTC-USD", side="buy", size_usd=100.0, strategy="RSI", timeout=0.1
        )
        self.assertTrue(token1.granted)

        # Same parameters while token1 is still held → slot busy.
        token2 = self.seak.acquire(
            symbol="BTC-USD", side="buy", size_usd=100.0, strategy="RSI", timeout=0.05
        )
        self.assertFalse(token2.granted)
        self.assertEqual(token2.rejection_reason, RejectionReason.SLOT_BUSY)
        self.seak.release(token1)

    def test_after_release_same_params_allowed(self):
        """After a token is released the fingerprint is cleared, so the same
        parameters may be acquired again (legitimate re-entry)."""
        token1 = self.seak.acquire(
            symbol="BTC-USD", side="buy", size_usd=100.0, strategy="RSI"
        )
        self.assertTrue(token1.granted)
        self.seak.release(token1)

        # After release fingerprint is cleared — re-entry must be allowed.
        token2 = self.seak.acquire(
            symbol="BTC-USD", side="buy", size_usd=100.0, strategy="RSI"
        )
        self.assertTrue(token2.granted)
        self.seak.release(token2)

    def test_different_strategy_not_duplicate(self):
        token1 = self.seak.acquire(
            symbol="BTC-USD", side="buy", size_usd=100.0, strategy="RSI"
        )
        self.assertTrue(token1.granted)
        self.seak.release(token1)

        # Different strategy → different fingerprint (and also slot is free).
        token2 = self.seak.acquire(
            symbol="BTC-USD", side="buy", size_usd=100.0, strategy="MACD"
        )
        self.assertTrue(token2.granted)
        self.seak.release(token2)


class TestLowLevelSlotAPI(unittest.TestCase):
    def setUp(self):
        self.seak = _fresh_seak()

    def test_claim_and_release(self):
        slot = self.seak.claim_execution_slot("BTC-USD", caller="test")
        self.assertTrue(slot.granted)
        self.seak.release_execution_slot(slot)

    def test_busy_slot_denied(self):
        slot1 = self.seak.claim_execution_slot("BTC-USD", caller="a", timeout=0.1)
        self.assertTrue(slot1.granted)

        slot2 = self.seak.claim_execution_slot("BTC-USD", caller="b", timeout=0.05)
        self.assertFalse(slot2.granted)
        self.assertEqual(slot2.rejection_reason, RejectionReason.SLOT_BUSY)

        self.seak.release_execution_slot(slot1)

    def test_halted_kernel_denies_slot(self):
        self.seak.emergency_halt("low-level test")
        slot = self.seak.claim_execution_slot("BTC-USD", caller="test")
        self.assertFalse(slot.granted)
        self.assertEqual(slot.rejection_reason, RejectionReason.EMERGENCY_HALT)
        self.seak.resume()


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self.seak = _fresh_seak()

    def test_approved_entry_recorded(self):
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0, strategy="S1")
        self.seak.release(token)
        log = self.seak.get_audit_log()
        outcomes = [e["outcome"] for e in log]
        self.assertIn(AuditOutcome.APPROVED.value, outcomes)

    def test_released_entry_recorded(self):
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.seak.release(token)
        log = self.seak.get_audit_log()
        outcomes = [e["outcome"] for e in log]
        self.assertIn(AuditOutcome.RELEASED.value, outcomes)

    def test_rejected_entry_recorded(self):
        self.seak.emergency_halt("audit test")
        self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.seak.resume()
        log = self.seak.get_audit_log()
        outcomes = [e["outcome"] for e in log]
        self.assertIn(AuditOutcome.REJECTED.value, outcomes)

    def test_halt_resume_recorded(self):
        self.seak.emergency_halt("audit halt")
        self.seak.resume("tester")
        log = self.seak.get_audit_log()
        outcomes = [e["outcome"] for e in log]
        self.assertIn(AuditOutcome.HALT.value, outcomes)
        self.assertIn(AuditOutcome.RESUME.value, outcomes)

    def test_last_n_limit(self):
        for i in range(10):
            t = self.seak.acquire(symbol=f"COIN{i}-USD", side="buy", size_usd=10.0)
            self.seak.release(t)
        log = self.seak.get_audit_log(last_n=3)
        self.assertLessEqual(len(log), 3)


class TestStatusSnapshot(unittest.TestCase):
    def setUp(self):
        self.seak = _fresh_seak()

    def test_status_fields_present(self):
        status = self.seak.get_status()
        for key in ("halted", "active_slots", "total_approved", "total_rejected",
                    "total_released", "guards"):
            self.assertIn(key, status)

    def test_counters_increment(self):
        before = self.seak.get_status()
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.seak.release(token)
        after = self.seak.get_status()
        self.assertEqual(after["total_approved"], before["total_approved"] + 1)
        self.assertEqual(after["total_released"], before["total_released"] + 1)

    def test_rejected_counter_increments(self):
        self.seak.emergency_halt("counter test")
        before = self.seak.get_status()
        self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        after = self.seak.get_status()
        self.assertEqual(after["total_rejected"], before["total_rejected"] + 1)
        self.seak.resume()


class TestHealthMonitorGuard(unittest.TestCase):
    """SEAK must block when health monitor says entries are not allowed."""

    def setUp(self):
        self.seak = _fresh_seak()

    def test_health_monitor_blocks_entry(self):
        mock_monitor = MagicMock()
        mock_decision = MagicMock()
        mock_decision.allow_entries = False
        mock_decision.reason = "API degraded"
        mock_monitor.check.return_value = mock_decision

        self.seak._health_monitor = mock_monitor
        self.seak._health_loaded = True

        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertFalse(token.granted)
        self.assertEqual(token.rejection_reason, RejectionReason.EXCHANGE_UNHEALTHY)

    def test_healthy_monitor_permits_entry(self):
        mock_monitor = MagicMock()
        mock_decision = MagicMock()
        mock_decision.allow_entries = True
        mock_monitor.check.return_value = mock_decision

        self.seak._health_monitor = mock_monitor
        self.seak._health_loaded = True

        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        self.seak.release(token)


class TestHardeningGuard(unittest.TestCase):
    """SEAK must block when the hardening layer rejects the order."""

    def setUp(self):
        self.seak = _fresh_seak()

    def test_hardening_rejection_blocks_entry(self):
        mock_hard = MagicMock()
        mock_hard.validate_order_hardening.return_value = (False, "position cap exceeded", {})

        self.seak._hardening = mock_hard
        self.seak._hardening_loaded = True

        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertFalse(token.granted)
        self.assertEqual(token.rejection_reason, RejectionReason.HARDENING_VIOLATION)

    def test_hardening_pass_permits_entry(self):
        mock_hard = MagicMock()
        mock_hard.validate_order_hardening.return_value = (True, "ok", {})

        self.seak._hardening = mock_hard
        self.seak._hardening_loaded = True

        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        self.seak.release(token)


class TestSingleton(unittest.TestCase):
    def test_get_seak_returns_same_instance(self):
        # Patch the module-level singleton so we don't pollute other tests.
        original = seak_mod._seak_instance
        seak_mod._seak_instance = None
        try:
            a = get_seak()
            b = get_seak()
            self.assertIs(a, b)
        finally:
            seak_mod._seak_instance = original


# ---------------------------------------------------------------------------
# Evidence: Successful lease acquisition
# ---------------------------------------------------------------------------


class TestLeaseAcquisition(unittest.TestCase):
    """
    Proves that a granted ExecutionToken constitutes a proper lease:
    - unique lease ID (request_id)
    - timestamps set at issuance
    - expiry is in the future
    - the APPROVED decision is written to the audit log
    """

    def setUp(self):
        self.seak = _fresh_seak()

    def test_lease_has_unique_request_id(self):
        """Every granted token carries a non-empty UUID that serves as the lease ID."""
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        self.assertNotEqual(token.request_id, "")
        parsed = _uuid.UUID(token.request_id)  # raises if not a valid UUID
        self.assertEqual(str(parsed), token.request_id)
        self.seak.release(token)

    def test_lease_issued_at_is_recent(self):
        """issued_at must be within the last 5 seconds of wall-clock time."""
        before = time.monotonic()
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        after = time.monotonic()
        self.assertTrue(token.granted)
        self.assertGreaterEqual(token.issued_at, before - _TIMING_TOLERANCE_S)
        self.assertLessEqual(token.issued_at, after + _TIMING_TOLERANCE_S)
        self.seak.release(token)

    def test_lease_expires_at_is_after_issued_at(self):
        """expires_at must be strictly after issued_at (the lease has a TTL)."""
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        self.assertGreater(token.expires_at, token.issued_at)
        self.seak.release(token)

    def test_lease_audit_log_records_approved(self):
        """APPROVED entry must appear in the audit log with the token's request_id."""
        token = self.seak.acquire(
            symbol="BTC-USD", side="buy", size_usd=100.0, strategy="RSI", caller="test_lease"
        )
        self.assertTrue(token.granted)
        log = self.seak.get_audit_log()
        approved_entries = [e for e in log if e["outcome"] == AuditOutcome.APPROVED.value]
        matching = [e for e in approved_entries if e["request_id"] == token.request_id]
        self.assertEqual(len(matching), 1, "Expected exactly one APPROVED entry for this lease")
        entry = matching[0]
        self.assertEqual(entry["symbol"], "BTC-USD")
        self.assertEqual(entry["side"], "buy")
        self.assertEqual(entry["strategy"], "RSI")
        self.assertEqual(entry["caller"], "test_lease")
        self.seak.release(token)

    def test_sequential_leases_have_distinct_ids(self):
        """Two successive acquisitions must produce tokens with different request_ids."""
        token1 = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.seak.release(token1)
        token2 = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.seak.release(token2)
        self.assertTrue(token1.granted)
        self.assertTrue(token2.granted)
        self.assertNotEqual(token1.request_id, token2.request_id)


# ---------------------------------------------------------------------------
# Evidence: Fencing token issuance
# ---------------------------------------------------------------------------


class TestFencingTokenIssuance(unittest.TestCase):
    """
    Proves that SEAK issues a fencing token (request_id UUID) on every grant,
    and that denied requests carry no usable fencing token (granted=False).
    """

    def setUp(self):
        self.seak = _fresh_seak()

    def test_granted_token_carries_fencing_id(self):
        """A granted token's request_id is the fencing token: non-empty UUID."""
        token = self.seak.acquire(symbol="ETH-USD", side="sell", size_usd=200.0)
        self.assertTrue(token.granted)
        self.assertNotEqual(token.request_id, "")
        _uuid.UUID(token.request_id)  # raises ValueError if not valid UUID
        self.seak.release(token)

    def test_fencing_tokens_are_unique_per_symbol(self):
        """Fencing tokens for concurrent slots on different symbols must differ."""
        token_btc = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        token_eth = self.seak.acquire(symbol="ETH-USD", side="buy", size_usd=100.0)
        self.assertTrue(token_btc.granted)
        self.assertTrue(token_eth.granted)
        self.assertNotEqual(token_btc.request_id, token_eth.request_id)
        _uuid.UUID(token_btc.request_id)
        _uuid.UUID(token_eth.request_id)
        self.seak.release(token_btc)
        self.seak.release(token_eth)

    def test_denied_token_has_no_granted_flag(self):
        """A rejection must not grant execution authority; granted must be False."""
        self.seak.emergency_halt("fencing test")
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertFalse(token.granted)
        self.assertEqual(token.rejection_reason, RejectionReason.EMERGENCY_HALT)
        self.seak.resume()

    def test_fencing_token_fields_populated(self):
        """symbol, side, size_usd, issued_at, and expires_at are all set on grant."""
        token = self.seak.acquire(
            symbol="SOL-USD", side="sell", size_usd=50.0,
            strategy="APEX", caller="fencing_test"
        )
        self.assertTrue(token.granted)
        self.assertEqual(token.symbol, "SOL-USD")
        self.assertEqual(token.side, "sell")
        self.assertEqual(token.size_usd, 50.0)
        self.assertEqual(token.strategy, "APEX")
        self.assertEqual(token.caller, "fencing_test")
        self.assertGreater(token.expires_at, 0)
        self.assertGreater(token.issued_at, 0)
        self.seak.release(token)


# ---------------------------------------------------------------------------
# Evidence: Execution unlock boundary
# ---------------------------------------------------------------------------


class TestExecutionUnlockBoundary(unittest.TestCase):
    """
    Proves that execution_authority_scope() correctly marks the execution
    context: has_execution_authority() returns True only inside the scope,
    and the boundary is thread-local (uses contextvars).
    """

    def test_no_authority_outside_scope(self):
        """Outside of any execution_authority_scope, authority must be False."""
        from bot.execution_authority_context import has_execution_authority
        self.assertFalse(has_execution_authority())

    def test_authority_true_inside_scope(self):
        """Inside execution_authority_scope, has_execution_authority must return True."""
        from bot.execution_authority_context import (
            execution_authority_scope,
            has_execution_authority,
        )
        with execution_authority_scope():
            self.assertTrue(has_execution_authority())

    def test_authority_false_after_scope_exits(self):
        """After execution_authority_scope exits, authority must revert to False."""
        from bot.execution_authority_context import (
            execution_authority_scope,
            has_execution_authority,
        )
        with execution_authority_scope():
            pass
        self.assertFalse(has_execution_authority())

    def test_authority_false_after_scope_exception(self):
        """Authority must revert to False even when the scope exits via an exception."""
        from bot.execution_authority_context import (
            execution_authority_scope,
            has_execution_authority,
        )
        try:
            with execution_authority_scope():
                raise ValueError("simulated trade error")
        except ValueError:
            pass
        self.assertFalse(has_execution_authority())

    def test_scope_is_not_inherited_by_child_thread(self):
        """A new thread starts with no authority even when the parent holds the scope."""
        from bot.execution_authority_context import (
            execution_authority_scope,
            has_execution_authority,
        )
        child_result: list = []

        def child():
            child_result.append(has_execution_authority())

        with execution_authority_scope():
            t = threading.Thread(target=child)
            t.start()
            t.join()

        # Child thread started without authority (ContextVar isolation).
        self.assertFalse(child_result[0])

    def test_nested_scopes_restore_correctly(self):
        """Nested execution_authority_scope calls restore state properly on exit."""
        from bot.execution_authority_context import (
            execution_authority_scope,
            has_execution_authority,
        )
        self.assertFalse(has_execution_authority())
        with execution_authority_scope():
            self.assertTrue(has_execution_authority())
            with execution_authority_scope():
                self.assertTrue(has_execution_authority())
            # Inner scope exited — outer scope should still hold authority.
            self.assertTrue(has_execution_authority())
        self.assertFalse(has_execution_authority())

    def test_startup_write_authority_allows_ready_prerequisites_without_scope(self):
        """Startup authority must allow validated startup prerequisites pre-scope."""
        from bot.execution_authority_context import assert_startup_write_authority

        with patch(
            "bot.execution_authority_context.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_authority_context.get_startup_execution_authority_prerequisites",
            return_value={"ready": True, "missing": []},
        ), patch(
            "bot.execution_authority_context.get_seak",
            return_value=None,
        ):
            assert_startup_write_authority()

    def test_startup_write_authority_blocks_when_prerequisites_not_ready(self):
        """Startup authority must fail closed when prerequisites are incomplete."""
        from bot.execution_authority_context import assert_startup_write_authority

        with patch(
            "bot.execution_authority_context.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_authority_context.get_startup_execution_authority_prerequisites",
            return_value={"ready": False, "missing": ["heartbeat_active"]},
        ), patch(
            "bot.execution_authority_context.get_seak",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                assert_startup_write_authority()
            self.assertIn("Startup execution authority unavailable", str(ctx.exception))
            self.assertIn("heartbeat_active", str(ctx.exception))


# ---------------------------------------------------------------------------
# Evidence: Continuous authority heartbeat enforcement
# ---------------------------------------------------------------------------


class TestContinuousAuthorityHeartbeatEnforcement(unittest.TestCase):
    """
    Proves that the execution authority is time-bounded (heartbeat-enforced):
    - Every granted token has a finite expires_at (lease TTL).
    - A slot whose expires_at has elapsed is detected and force-released by
      the reaper, freeing the symbol for the next legitimate caller.
    - The TTL boundary is respected: a token that has NOT yet expired keeps
      the slot locked, while one that HAS expired is reaped.
    """

    def setUp(self):
        self.seak = _fresh_seak()

    def test_token_has_finite_expiry(self):
        """Every granted token must carry a positive, finite expires_at TTL."""
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)
        self.assertGreater(token.expires_at, time.monotonic())
        # TTL must be bounded (default is _SLOT_TIMEOUT_S = 30 s; accept up to _MAX_TTL_S).
        self.assertLess(token.expires_at - time.monotonic(), _MAX_TTL_S)
        self.seak.release(token)

    def test_reaper_force_releases_expired_slot(self):
        """
        A slot whose expires_at is in the past must be force-released by the
        reaper so that the next caller can acquire the symbol immediately.
        """
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)

        # Simulate heartbeat timeout: wind back the slot's expires_at.
        slot = self.seak._slots.get("BTC-USD")
        self.assertIsNotNone(slot)
        slot.expires_at = time.monotonic() - 1.0  # already expired

        # Run the reaper directly (no need to wait 15 s).
        self.seak._reap_timed_out_slots()

        # The slot must now be free — a new acquire should succeed.
        token2 = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=200.0, timeout=0.1)
        self.assertTrue(token2.granted, "Reaper should have freed the expired slot")
        self.seak.release(token2)

    def test_unexpired_slot_not_reaped(self):
        """
        A slot whose expires_at is in the future must NOT be reaped; the symbol
        remains locked until explicitly released.
        """
        token = self.seak.acquire(symbol="ETH-USD", side="buy", size_usd=100.0, timeout=0.1)
        self.assertTrue(token.granted)

        # Reaper runs while the slot is still valid.
        self.seak._reap_timed_out_slots()

        # Symbol must still be locked — second acquire should time out.
        token2 = self.seak.acquire(symbol="ETH-USD", side="buy", size_usd=100.0, timeout=0.05)
        self.assertFalse(token2.granted)
        self.assertEqual(token2.rejection_reason, RejectionReason.SLOT_BUSY)

        self.seak.release(token)

    def test_force_released_count_increments_after_reap(self):
        """force_release count must increase after the reaper expires a slot."""
        token = self.seak.acquire(symbol="BTC-USD", side="buy", size_usd=100.0)
        self.assertTrue(token.granted)

        before_count = self.seak._total_force_released

        slot = self.seak._slots.get("BTC-USD")
        self.assertIsNotNone(slot)
        slot.expires_at = time.monotonic() - 1.0

        self.seak._reap_timed_out_slots()

        self.assertGreater(self.seak._total_force_released, before_count)


if __name__ == "__main__":
    unittest.main()
