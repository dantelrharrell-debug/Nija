"""
Tests for nonce reconnect resync — ConnectionStabilityManager hooks and
KrakenBroker._nonce_reconnect_resync().

Covers:
  - register_pre_reconnect_hook / register_reconnect_hook registration
  - _fire_pre_reconnect_hooks fires before reconnect_fn
  - _fire_reconnect_hooks fires after successful reconnect
  - Hook exceptions are caught and do not abort the reconnect
  - _nonce_reconnect_resync classifies SYNCED / DRIFTED / BEHIND / UNKNOWN
  - _nonce_reconnect_resync calls probe_server_sync on BEHIND / UNKNOWN
  - _nonce_reconnect_resync skips resync on SYNCED / DRIFTED
  - _nonce_reconnect_resync handles missing nonce manager gracefully
  - _nonce_reconnect_resync respects timeout guard
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, call, patch

from bot.connection_stability_manager import (
    ConnectionStabilityManager,
    ConnectionState,
    WatchdogConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csm(broker_name: str = "test_broker") -> ConnectionStabilityManager:
    """Return a CSM with a very short watchdog interval for testing."""
    cfg = WatchdogConfig(
        check_interval_s=0.05,
        failure_threshold=2,
        reconnect_base_delay_s=0.01,
        reconnect_max_delay_s=0.05,
        max_reconnect_attempts=3,
    )
    return ConnectionStabilityManager(broker_name=broker_name, watchdog_cfg=cfg)


# ---------------------------------------------------------------------------
# ConnectionStabilityManager hook tests
# ---------------------------------------------------------------------------

class TestConnectionStabilityManagerHooks(unittest.TestCase):

    def test_register_pre_reconnect_hook_stored(self):
        csm = _make_csm()
        hook = MagicMock()
        csm.register_pre_reconnect_hook(hook)
        self.assertIn(hook, csm._pre_reconnect_hooks)

    def test_register_reconnect_hook_stored(self):
        csm = _make_csm()
        hook = MagicMock()
        csm.register_reconnect_hook(hook)
        self.assertIn(hook, csm._reconnect_hooks)

    def test_fire_pre_reconnect_hooks_calls_all(self):
        csm = _make_csm()
        h1, h2 = MagicMock(), MagicMock()
        csm.register_pre_reconnect_hook(h1)
        csm.register_pre_reconnect_hook(h2)
        csm._fire_pre_reconnect_hooks()
        h1.assert_called_once_with()
        h2.assert_called_once_with()

    def test_fire_reconnect_hooks_calls_all(self):
        csm = _make_csm()
        h1, h2 = MagicMock(), MagicMock()
        csm.register_reconnect_hook(h1)
        csm.register_reconnect_hook(h2)
        csm._fire_reconnect_hooks()
        h1.assert_called_once_with()
        h2.assert_called_once_with()

    def test_pre_reconnect_hook_exception_does_not_abort(self):
        csm = _make_csm()
        bad_hook = MagicMock(side_effect=RuntimeError("boom"))
        good_hook = MagicMock()
        csm.register_pre_reconnect_hook(bad_hook)
        csm.register_pre_reconnect_hook(good_hook)
        # Should not raise
        csm._fire_pre_reconnect_hooks()
        good_hook.assert_called_once_with()

    def test_reconnect_hook_exception_does_not_abort(self):
        csm = _make_csm()
        bad_hook = MagicMock(side_effect=RuntimeError("boom"))
        good_hook = MagicMock()
        csm.register_reconnect_hook(bad_hook)
        csm.register_reconnect_hook(good_hook)
        csm._fire_reconnect_hooks()
        good_hook.assert_called_once_with()

    def test_attempt_reconnect_fires_pre_hook_before_reconnect_fn(self):
        """Pre-reconnect hook must fire before reconnect_fn is called."""
        csm = _make_csm()
        call_order = []

        def pre_hook():
            call_order.append("pre")

        def reconnect_fn():
            call_order.append("reconnect")
            return True

        csm.register_broker(broker=MagicMock(), reconnect_fn=reconnect_fn)
        csm.register_pre_reconnect_hook(pre_hook)
        csm._attempt_reconnect()
        self.assertEqual(call_order, ["pre", "reconnect"])

    def test_attempt_reconnect_fires_post_hook_on_success(self):
        """Post-reconnect hook must fire after a successful reconnect."""
        csm = _make_csm()
        post_hook = MagicMock()
        csm.register_broker(broker=MagicMock(), reconnect_fn=lambda: True)
        csm.register_reconnect_hook(post_hook)
        result = csm._attempt_reconnect()
        self.assertTrue(result)
        post_hook.assert_called_once_with()

    def test_attempt_reconnect_does_not_fire_post_hook_on_failure(self):
        """Post-reconnect hook must NOT fire when all reconnect attempts fail."""
        csm = _make_csm()
        post_hook = MagicMock()
        csm.register_broker(broker=MagicMock(), reconnect_fn=lambda: False)
        csm.register_reconnect_hook(post_hook)
        result = csm._attempt_reconnect()
        self.assertFalse(result)
        post_hook.assert_not_called()

    def test_pre_hook_resets_connection_guard(self):
        """Simulate the _connection_already_complete reset pattern."""
        csm = _make_csm()
        broker = MagicMock()
        broker._connection_already_complete = True

        def reset_guard():
            broker._connection_already_complete = False

        csm.register_broker(broker=broker, reconnect_fn=lambda: True)
        csm.register_pre_reconnect_hook(reset_guard)
        csm._attempt_reconnect()
        self.assertFalse(broker._connection_already_complete)


# ---------------------------------------------------------------------------
# KrakenBroker._nonce_reconnect_resync tests
# ---------------------------------------------------------------------------

class _FakeDNM:
    """Minimal DistributedNonceManager stand-in for resync tests."""

    def __init__(self, last_nonce: int = 0, probe_raises: bool = False):
        self._last_nonce = last_nonce
        self._probe_calls: list = []
        self._probe_raises = probe_raises

    def get_last_nonce(self, key_id: str) -> int:
        return self._last_nonce

    def probe_server_sync(self, key_id: str) -> None:
        if self._probe_raises:
            raise RuntimeError("probe failed")
        self._probe_calls.append(key_id)
        # Simulate re-anchoring to now_ms
        self._last_nonce = int(time.time() * 1000) + 5000


def _make_fake_broker(nonce_manager=None, api_key_id: str = "testkey"):
    """Return a minimal object that exposes _nonce_reconnect_resync from KrakenBroker."""
    # Import lazily to avoid heavy broker_manager import at module level.
    from bot.broker_manager import KrakenBroker

    class _FakeKrakenBroker:
        account_identifier = "TEST"

        def __init__(self):
            self.nonce_manager = nonce_manager
            self.api_key_id = api_key_id

        _nonce_reconnect_resync = KrakenBroker._nonce_reconnect_resync

    return _FakeKrakenBroker()


class TestNonceReconnectResync(unittest.TestCase):

    def _run_resync(self, broker):
        """Run _nonce_reconnect_resync synchronously (it spawns a thread internally)."""
        broker._nonce_reconnect_resync()

    def test_synced_state_no_resync(self):
        """Nonce within threshold of now_ms → SYNCED, no probe_server_sync call."""
        now_ms = int(time.time() * 1000)
        dnm = _FakeDNM(last_nonce=now_ms)  # delta = 0 → SYNCED
        broker = _make_fake_broker(nonce_manager=dnm)
        self._run_resync(broker)
        self.assertEqual(dnm._probe_calls, [])

    def test_drifted_state_no_resync(self):
        """Nonce ahead of now_ms by > threshold → DRIFTED, no probe_server_sync call."""
        now_ms = int(time.time() * 1000)
        dnm = _FakeDNM(last_nonce=now_ms + 60_000)  # 60s ahead → DRIFTED
        broker = _make_fake_broker(nonce_manager=dnm)
        self._run_resync(broker)
        self.assertEqual(dnm._probe_calls, [])

    def test_behind_state_triggers_resync(self):
        """Nonce behind now_ms by > threshold → BEHIND, probe_server_sync called."""
        now_ms = int(time.time() * 1000)
        dnm = _FakeDNM(last_nonce=now_ms - 60_000)  # 60s behind → BEHIND
        broker = _make_fake_broker(nonce_manager=dnm)
        self._run_resync(broker)
        self.assertEqual(dnm._probe_calls, ["testkey"])

    def test_unknown_state_triggers_resync(self):
        """last_nonce == 0 → UNKNOWN, probe_server_sync called."""
        dnm = _FakeDNM(last_nonce=0)
        broker = _make_fake_broker(nonce_manager=dnm)
        self._run_resync(broker)
        self.assertEqual(dnm._probe_calls, ["testkey"])

    def test_missing_nonce_manager_skips_gracefully(self):
        """No nonce_manager → skip without raising."""
        broker = _make_fake_broker(nonce_manager=None)
        # Should not raise
        self._run_resync(broker)

    def test_missing_api_key_id_skips_gracefully(self):
        """No api_key_id → skip without raising."""
        dnm = _FakeDNM(last_nonce=0)
        broker = _make_fake_broker(nonce_manager=dnm, api_key_id=None)
        self._run_resync(broker)
        self.assertEqual(dnm._probe_calls, [])

    def test_probe_exception_does_not_propagate(self):
        """probe_server_sync raising → logged, no exception escapes."""
        now_ms = int(time.time() * 1000)
        dnm = _FakeDNM(last_nonce=now_ms - 60_000, probe_raises=True)
        broker = _make_fake_broker(nonce_manager=dnm)
        # Should not raise
        self._run_resync(broker)

    def test_timeout_guard_does_not_block(self):
        """Resync that hangs is abandoned after timeout."""
        import os as _os

        class _SlowDNM(_FakeDNM):
            def get_last_nonce(self, key_id):
                time.sleep(5)  # simulate hang
                return 0

        _os.environ["NIJA_NONCE_RESYNC_TIMEOUT_S"] = "0.1"
        try:
            dnm = _SlowDNM(last_nonce=0)
            broker = _make_fake_broker(nonce_manager=dnm)
            start = time.monotonic()
            self._run_resync(broker)
            elapsed = time.monotonic() - start
            # Should return well within 1 second despite the 5s sleep
            self.assertLess(elapsed, 1.5)
        finally:
            _os.environ.pop("NIJA_NONCE_RESYNC_TIMEOUT_S", None)


if __name__ == "__main__":
    unittest.main()
