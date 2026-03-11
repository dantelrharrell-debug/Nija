"""
Tests for bot/trade_duplication_guard.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# Allow imports from bot/
sys.path.insert(0, str(Path(__file__).parent.parent))

from trade_duplication_guard import (
    TradeDuplicationGuard,
    TradeDuplicationGuardConfig,
    get_trade_duplication_guard,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg_short_ttl():
    """Config with a very short TTL for expiry tests."""
    return TradeDuplicationGuardConfig(
        ttl_seconds=0.2,
        size_decimals=6,
        max_pending=50,
        cleanup_interval_seconds=0,  # disable background reaper
    )


@pytest.fixture
def guard(cfg_short_ttl):
    """Fresh guard with short TTL and background cleanup disabled."""
    return TradeDuplicationGuard(cfg_short_ttl)


@pytest.fixture
def guard_default():
    """Guard with default (long) TTL."""
    cfg = TradeDuplicationGuardConfig(
        ttl_seconds=60.0,
        cleanup_interval_seconds=0,
    )
    return TradeDuplicationGuard(cfg)


# ---------------------------------------------------------------------------
# check_and_register — happy path
# ---------------------------------------------------------------------------


class TestCheckAndRegister:

    def test_first_submission_allowed(self, guard_default):
        allowed, reason = guard_default.check_and_register("BTC-USD", "buy", 0.001)
        assert allowed is True
        assert reason == "ok"

    def test_different_symbol_allowed(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        allowed, _ = guard_default.check_and_register("ETH-USD", "buy", 0.001)
        assert allowed is True

    def test_different_side_allowed(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        allowed, _ = guard_default.check_and_register("BTC-USD", "sell", 0.001)
        assert allowed is True

    def test_different_size_allowed(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        allowed, _ = guard_default.check_and_register("BTC-USD", "buy", 0.002)
        assert allowed is True

    def test_different_account_allowed(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001, "acc_1")
        allowed, _ = guard_default.check_and_register("BTC-USD", "buy", 0.001, "acc_2")
        assert allowed is True


# ---------------------------------------------------------------------------
# check_and_register — duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:

    def test_immediate_duplicate_blocked(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        allowed, reason = guard_default.check_and_register("BTC-USD", "buy", 0.001)
        assert allowed is False
        assert "duplicate" in reason.lower()

    def test_duplicate_reason_includes_symbol(self, guard_default):
        guard_default.check_and_register("ETH-USD", "sell", 1.0)
        _, reason = guard_default.check_and_register("ETH-USD", "sell", 1.0)
        assert "ETH-USD" in reason

    def test_duplicate_counts_attempts(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        guard_default.check_and_register("BTC-USD", "buy", 0.001)  # attempt 2
        _, reason = guard_default.check_and_register("BTC-USD", "buy", 0.001)  # attempt 3
        assert "#3" in reason or "attempt" in reason.lower()

    def test_symbol_case_insensitive(self, guard_default):
        guard_default.check_and_register("btc-usd", "buy", 0.001)
        allowed, _ = guard_default.check_and_register("BTC-USD", "buy", 0.001)
        assert allowed is False

    def test_side_case_insensitive(self, guard_default):
        guard_default.check_and_register("BTC-USD", "BUY", 0.001)
        allowed, _ = guard_default.check_and_register("BTC-USD", "buy", 0.001)
        assert allowed is False

    def test_float_noise_treated_as_same(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        # Tiny float difference below size_decimals precision → same fingerprint
        allowed, _ = guard_default.check_and_register("BTC-USD", "buy", 0.0010000001)
        assert allowed is False


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


class TestTTLExpiry:

    def test_resubmit_after_ttl_allowed(self, guard):
        guard.check_and_register("BTC-USD", "buy", 0.001)
        # Wait for TTL to expire (0.2s)
        time.sleep(0.3)
        allowed, _ = guard.check_and_register("BTC-USD", "buy", 0.001)
        assert allowed is True

    def test_blocked_within_ttl(self, guard):
        guard.check_and_register("BTC-USD", "buy", 0.001)
        # Immediately retry — still within TTL
        allowed, _ = guard.check_and_register("BTC-USD", "buy", 0.001)
        assert allowed is False


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


class TestRelease:

    def test_release_allows_resubmission(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        released = guard_default.release("BTC-USD", "buy", 0.001)
        assert released is True
        allowed, _ = guard_default.check_and_register("BTC-USD", "buy", 0.001)
        assert allowed is True

    def test_release_returns_false_if_not_registered(self, guard_default):
        result = guard_default.release("UNKNOWN-USD", "buy", 1.0)
        assert result is False

    def test_release_already_expired_slot_still_removes(self, guard):
        guard.check_and_register("BTC-USD", "buy", 0.001)
        time.sleep(0.3)   # expire it
        # The slot is still present in the dict (just past TTL); release removes it and returns True.
        # This is correct behaviour — the caller is confirming the trade is done.
        result = guard.release("BTC-USD", "buy", 0.001)
        assert result is True


# ---------------------------------------------------------------------------
# is_duplicate (read-only check)
# ---------------------------------------------------------------------------


class TestIsDuplicate:

    def test_not_duplicate_initially(self, guard_default):
        assert guard_default.is_duplicate("BTC-USD", "buy", 0.001) is False

    def test_duplicate_after_registration(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        assert guard_default.is_duplicate("BTC-USD", "buy", 0.001) is True

    def test_not_duplicate_after_release(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        guard_default.release("BTC-USD", "buy", 0.001)
        assert guard_default.is_duplicate("BTC-USD", "buy", 0.001) is False

    def test_not_duplicate_after_expiry(self, guard):
        guard.check_and_register("BTC-USD", "buy", 0.001)
        time.sleep(0.3)
        assert guard.is_duplicate("BTC-USD", "buy", 0.001) is False


# ---------------------------------------------------------------------------
# Capacity enforcement
# ---------------------------------------------------------------------------


class TestCapacity:

    def test_capacity_limit_enforced(self):
        cfg = TradeDuplicationGuardConfig(
            ttl_seconds=60.0,
            max_pending=3,
            cleanup_interval_seconds=0,
        )
        g = TradeDuplicationGuard(cfg)
        # Fill to capacity
        g.check_and_register("BTC-USD", "buy", 1.0, "acc_1")
        g.check_and_register("ETH-USD", "buy", 1.0, "acc_1")
        g.check_and_register("SOL-USD", "buy", 1.0, "acc_1")
        # Next should fail
        allowed, reason = g.check_and_register("ADA-USD", "buy", 1.0, "acc_1")
        assert allowed is False
        assert "capacity" in reason.lower()

    def test_expired_slots_freed_at_capacity(self):
        cfg = TradeDuplicationGuardConfig(
            ttl_seconds=0.1,
            max_pending=2,
            cleanup_interval_seconds=0,
        )
        g = TradeDuplicationGuard(cfg)
        g.check_and_register("BTC-USD", "buy", 1.0)
        g.check_and_register("ETH-USD", "buy", 1.0)
        time.sleep(0.2)  # expire existing slots
        # Should succeed because expired slots are evicted on capacity check
        allowed, _ = g.check_and_register("SOL-USD", "buy", 1.0)
        assert allowed is True


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:

    def test_reset_clears_all_slots(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        guard_default.check_and_register("ETH-USD", "sell", 1.0)
        guard_default.reset()
        assert guard_default.is_duplicate("BTC-USD", "buy", 0.001) is False
        assert guard_default.is_duplicate("ETH-USD", "sell", 1.0) is False

    def test_reset_clears_blocked_log(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        guard_default.check_and_register("BTC-USD", "buy", 0.001)  # blocked
        guard_default.reset()
        status = guard_default.get_status()
        assert status["total_blocked"] == 0


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:

    def test_status_keys(self, guard_default):
        status = guard_default.get_status()
        expected = {"pending_fingerprints", "max_pending", "ttl_seconds",
                    "total_blocked", "recent_blocked"}
        assert expected.issubset(status.keys())

    def test_pending_count(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        guard_default.check_and_register("ETH-USD", "buy", 0.001)
        status = guard_default.get_status()
        assert status["pending_fingerprints"] == 2

    def test_blocked_count_increments(self, guard_default):
        guard_default.check_and_register("BTC-USD", "buy", 0.001)
        guard_default.check_and_register("BTC-USD", "buy", 0.001)  # blocked
        guard_default.check_and_register("BTC-USD", "buy", 0.001)  # blocked again
        status = guard_default.get_status()
        assert status["total_blocked"] == 2


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:

    def test_concurrent_submissions_one_wins(self, guard_default):
        """Only the first concurrent submission of the same trade should succeed."""
        import threading

        results = []
        barrier = threading.Barrier(10)

        def submit():
            barrier.wait()  # synchronise start
            allowed, _ = guard_default.check_and_register("BTC-USD", "buy", 0.001)
            results.append(allowed)

        threads = [threading.Thread(target=submit) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one should succeed
        assert results.count(True) == 1
        assert results.count(False) == 9
