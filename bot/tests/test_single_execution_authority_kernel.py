"""
Tests for the Single Execution Authority Kernel (SEAK).
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
