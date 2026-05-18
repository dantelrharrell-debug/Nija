"""
Tests for capital-authority recovery-aware nonce-rebuild cooldown handling.

Validates that CapitalAuthority.refresh() treats bounded Kraken nonce-manager
rebuild cooldown windows as a recovery state rather than a connectivity failure,
i.e. the CA must:

1. Preserve its own cached balance when a zero is returned by the broker
   because the nonce-manager is in a rebuild cooldown (detected via
   _get_kraken_nonce_rebuild_cooldown_remaining_s() > 0).

2. Preserve its own cached balance when broker.get_account_balance() raises
   a nonce-rebuild cooldown exception (detected via
   _get_nonce_rebuild_cooldown_seconds_from_exception()).

3. Fall back to the normal can_preserve_previous / store-zero logic when
   the nonce module reports no active cooldown.

4. Never preserve a stale/old zero when there is no cached CA balance to
   preserve (previous == 0.0), regardless of cooldown state.
"""

import sys
import os
import threading
import time
import datetime
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.capital_authority import (
    CapitalAuthority,
    _get_kraken_nonce_rebuild_cooldown_remaining_s,
    _get_nonce_rebuild_cooldown_seconds_from_exception,
)
import bot.capital_authority as _ca_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_stub_broker_manager():
    """Return a minimal broker-manager stub that satisfies the refresh() guards."""
    bm = MagicMock()
    bm.has_registered_sources.return_value = True
    bm.has_registered_brokers.return_value = True
    bm._capital_bootstrap_barrier_started_at = None
    bm.capital_startup_invariant_timeout_s = 0.0
    bm.refresh_registry.return_value = None
    return bm


def _make_authority_with_balance(broker_key: str, balance: float) -> CapitalAuthority:
    """Return a CapitalAuthority stub pre-seeded with a cached balance.

    Bypasses the singleton guard (resets _EXPECTED_ID) and satisfies all
    attributes checked by refresh().
    """
    # Reset the module-level singleton ID so this fresh instance passes assert_singleton().
    _ca_mod._EXPECTED_ID = None

    ca = CapitalAuthority.__new__(CapitalAuthority)
    ca._lock = threading.RLock()
    ca._lock_timeout = 5.0
    ca._startup_lock = threading.Event()
    ca._startup_lock.set()  # allow refresh without startup-lock warning
    ca.broker_manager = None  # will be set from get_broker_manager() stub
    ca._reserve_pct = 0.0
    ca._broker_balances = {broker_key: balance}
    ca._broker_roles = {}
    ca._open_exposure_usd = 0.0
    ca._last_updated_total = balance
    ca.last_updated = datetime.datetime.now(datetime.timezone.utc)
    ca._expected_brokers = 1
    ca._opportunistic = False
    ca._hydrated = balance > 0.0
    ca._preserve_nonzero_ttl_s = 180.0
    ca._last_typed_snapshot = None
    ca._broker_feed_timestamps = {}
    ca._balance_feeds = {}
    ca._broker_registration_complete = threading.Event()
    ca._broker_registration_complete.set()
    ca._warm_start = False
    ca._pending_feeds = []
    return ca


def _make_stub_bm_and_patch():
    """Return (stub_bm, ctx) where ctx is a started patch context."""
    stub_bm = _build_stub_broker_manager()
    p = patch(
        "bot.multi_account_broker_manager.get_broker_manager",
        return_value=stub_bm,
    )
    p.start()
    return stub_bm, p


class _ZeroBroker:
    """Broker stub that always returns 0.0 (no cached balance during cooldown)."""

    def get_account_balance(self):
        return 0.0


class _NonceCooldownExceptionBroker:
    """Broker stub that raises a nonce-rebuild cooldown RuntimeError."""

    def __init__(self, cooldown_s: float = 29.0, variant: str = "suppressed"):
        self._cooldown_s = cooldown_s
        self._variant = variant

    def get_account_balance(self):
        if self._variant == "suppressed":
            raise RuntimeError(
                "KrakenNonceManager singleton was destroyed and previous rebuild failed; "
                f"retry suppressed for {self._cooldown_s}s cooldown."
            )
        raise RuntimeError(
            "KrakenNonceManager singleton was destroyed and rebuild failed; "
            f"retry cooldown {self._cooldown_s}s activated."
        )


class _LiveBroker:
    """Broker stub that returns a positive balance."""

    def __init__(self, balance: float = 1000.0):
        self._balance = balance

    def get_account_balance(self):
        return self._balance


class _FailBroker:
    """Broker stub that raises a generic connectivity error."""

    def get_account_balance(self):
        raise RuntimeError("Generic connectivity error")


# ---------------------------------------------------------------------------
# Tests for the module-level helpers
# ---------------------------------------------------------------------------


class TestNonceCooldownHelpers(unittest.TestCase):
    def test_exception_helper_detects_retry_suppressed(self):
        exc = RuntimeError(
            "KrakenNonceManager singleton was destroyed and previous rebuild failed; "
            "retry suppressed for 29.0s cooldown."
        )
        self.assertAlmostEqual(
            _get_nonce_rebuild_cooldown_seconds_from_exception(exc), 29.0
        )

    def test_exception_helper_detects_cooldown_activated(self):
        exc = RuntimeError(
            "KrakenNonceManager singleton was destroyed and rebuild failed; "
            "retry cooldown 30.0s activated."
        )
        self.assertAlmostEqual(
            _get_nonce_rebuild_cooldown_seconds_from_exception(exc), 30.0
        )

    def test_exception_helper_returns_zero_for_unrelated_exception(self):
        exc = RuntimeError("Generic connection error")
        self.assertEqual(_get_nonce_rebuild_cooldown_seconds_from_exception(exc), 0.0)

    def test_exception_helper_walks_cause_chain(self):
        inner = RuntimeError(
            "KrakenNonceManager singleton was destroyed and previous rebuild failed; "
            "retry suppressed for 15.0s cooldown."
        )
        outer = RuntimeError("wrapper error")
        outer.__cause__ = inner
        self.assertAlmostEqual(
            _get_nonce_rebuild_cooldown_seconds_from_exception(outer), 15.0
        )

    def test_kraken_nonce_cooldown_remaining_returns_float(self):
        # Should always return a non-negative float (may be 0.0 when module
        # is unavailable or no cooldown is active in the test environment).
        result = _get_kraken_nonce_rebuild_cooldown_remaining_s()
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, 0.0)


# ---------------------------------------------------------------------------
# Tests for recovery-aware refresh() behaviour — zero-balance path
# ---------------------------------------------------------------------------


class TestCapitalAuthorityNonceCooldownZeroBalancePath(unittest.TestCase):
    """refresh() preserves CA-cached balance when broker returns 0.0 during cooldown."""

    def setUp(self):
        self._stub_bm, self._patch = _make_stub_bm_and_patch()

    def tearDown(self):
        self._patch.stop()
        # Restore singleton state so the next test can create a fresh CA.
        _ca_mod._EXPECTED_ID = None

    def _refresh_with_cooldown(self, ca, broker, cooldown_s: float) -> None:
        """Patch the module-level cooldown helper, call refresh(), then restore."""
        original = _ca_mod._get_kraken_nonce_rebuild_cooldown_remaining_s
        _ca_mod._get_kraken_nonce_rebuild_cooldown_remaining_s = lambda: cooldown_s
        try:
            ca.broker_manager = self._stub_bm
            ca.refresh({"kraken": broker})
        finally:
            _ca_mod._get_kraken_nonce_rebuild_cooldown_remaining_s = original

    def test_preserves_cached_balance_when_cooldown_active_and_broker_returns_zero(self):
        ca = _make_authority_with_balance("kraken", 500.0)
        self._refresh_with_cooldown(ca, _ZeroBroker(), cooldown_s=25.0)
        self.assertAlmostEqual(ca.get_raw_per_broker("kraken"), 500.0)

    def test_does_not_preserve_when_cooldown_cleared_and_previous_ttl_expired(self):
        ca = _make_authority_with_balance("kraken", 500.0)
        # Force the previous balance to be considered stale (age > TTL).
        ca.last_updated = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=300)
        # Cooldown is NOT active.
        self._refresh_with_cooldown(ca, _ZeroBroker(), cooldown_s=0.0)
        # Without cooldown, previous is too old → confirmed zero stored (broker
        # returned an explicit 0.0, so FIX-3 path: store zero, not skip).
        self.assertAlmostEqual(ca.get_raw_per_broker("kraken"), 0.0)

    def test_does_not_preserve_when_previous_is_zero_and_cooldown_active(self):
        # No meaningful cached balance — cooldown cannot help here.
        ca = _make_authority_with_balance("kraken", 0.0)
        self._refresh_with_cooldown(ca, _ZeroBroker(), cooldown_s=29.0)
        # Previous was 0.0 → nothing to preserve → confirmed zero stored.
        self.assertAlmostEqual(ca.get_raw_per_broker("kraken"), 0.0)

    def test_normal_positive_balance_not_affected_by_cooldown_detection(self):
        ca = _make_authority_with_balance("kraken", 200.0)
        self._refresh_with_cooldown(ca, _LiveBroker(balance=750.0), cooldown_s=29.0)
        # Live balance > 0 → normal path: stored directly.
        self.assertAlmostEqual(ca.get_raw_per_broker("kraken"), 750.0)


# ---------------------------------------------------------------------------
# Tests for recovery-aware refresh() behaviour — exception path
# ---------------------------------------------------------------------------


class TestCapitalAuthorityNonceCooldownExceptionPath(unittest.TestCase):
    """refresh() preserves CA-cached balance when broker raises nonce cooldown error."""

    def setUp(self):
        self._stub_bm, self._patch = _make_stub_bm_and_patch()

    def tearDown(self):
        self._patch.stop()
        _ca_mod._EXPECTED_ID = None

    def _refresh(self, ca, broker):
        ca.broker_manager = self._stub_bm
        ca.refresh({"kraken": broker})

    def test_preserves_cached_balance_on_retry_suppressed_exception(self):
        ca = _make_authority_with_balance("kraken", 321.0)
        self._refresh(ca, _NonceCooldownExceptionBroker(29.0, "suppressed"))
        self.assertAlmostEqual(ca.get_raw_per_broker("kraken"), 321.0)

    def test_preserves_cached_balance_on_cooldown_activated_exception(self):
        ca = _make_authority_with_balance("kraken", 321.0)
        self._refresh(ca, _NonceCooldownExceptionBroker(30.0, "activated"))
        self.assertAlmostEqual(ca.get_raw_per_broker("kraken"), 321.0)

    def test_no_preserve_when_no_previous_balance_and_cooldown_exception(self):
        ca = _make_authority_with_balance("kraken", 0.0)
        self._refresh(ca, _NonceCooldownExceptionBroker(29.0, "suppressed"))
        # No cached CA balance → broker excluded → real capital remains 0.
        self.assertAlmostEqual(ca.get_real_capital(), 0.0)

    def test_unrelated_exception_falls_through_to_can_preserve_previous(self):
        ca = _make_authority_with_balance("kraken", 400.0)
        # previous is 400.0 and last_updated is recent → can_preserve_previous=True.
        self._refresh(ca, _FailBroker())
        # Not a nonce cooldown → normal TTL-based preserve.
        self.assertAlmostEqual(ca.get_raw_per_broker("kraken"), 400.0)

    def test_unrelated_exception_does_not_preserve_stale_previous(self):
        ca = _make_authority_with_balance("kraken", 400.0)
        # Force previous to be stale (age > _preserve_nonzero_ttl_s).
        ca.last_updated = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=300)
        )
        self._refresh(ca, _FailBroker())
        # Stale previous + not a cooldown → broker excluded from new_balances.
        # refresh() returns early ("keeping prior state") without updating
        # last_updated, so the CA becomes stale.  The old cached value is
        # retained (not cleared to 0) — phantom-zero transitions are never
        # introduced by the CA.
        self.assertTrue(
            ca.is_stale(ttl_s=60.0),
            "CA must be stale when refresh produced no broker balances",
        )


if __name__ == "__main__":
    unittest.main()
