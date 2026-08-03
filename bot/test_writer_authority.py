"""Regression tests for distributed writer authority.

Tests cover:
  1. Normal startup        – single instance acquires lock and emits LOCK_ACQUIRED
  2. Graceful failover     – first writer releases; second immediately acquires
  3. Stale-lock recovery   – lock held by a crashed (non-heartbeating) instance;
                             new instance detects staleness, reclaims, and becomes
                             the active writer
  4. Split-brain prevention – two concurrent instances can never both hold the
                              distributed writer lock simultaneously

All tests use ``fakeredis`` (with Lua scripting) to simulate Redis without a
live server.  The ``_connect_redis`` helper is monkey-patched so the module
under test never touches the network.

Requirements
------------
    pip install "fakeredis[lua]"
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import unittest
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Resolve import path regardless of invocation style
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import fakeredis  # noqa: F401  – availability guard
except ImportError as _e:
    raise ImportError(
        "fakeredis[lua] is required to run these tests. "
        "Install it with: pip install 'fakeredis[lua]'"
    ) from _e

logging.basicConfig(level=logging.DEBUG)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_redis(server: Any | None = None) -> Any:
    """Return a FakeRedis client that shares *server* state when provided."""
    import fakeredis

    if server is None:
        server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _make_connect_redis_patch(client: Any):
    """Return a replacement for ``_connect_redis`` that yields *client*."""

    def _patched_connect(timeout_s: float = 3.0):  # noqa: ARG001
        return client, "redis://fake", ""

    return _patched_connect


def _make_instance_identity_patch(instance_id: str):
    """Return a replacement for ``_instance_identity`` for a specific ID."""

    def _patched():
        identity = {"instance_id": instance_id}
        owner = f"instance={instance_id}|pid=1"
        return identity, owner, instance_id

    return _patched


def _fresh_authority_module():
    """Import (or re-import) the module with a fresh singleton."""
    import importlib

    # Avoid stale singleton from a previous test
    mod_name = "bot.entrypoint_writer_authority"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    try:
        import bot.entrypoint_writer_authority as mod
    except ImportError:
        mod_name = "entrypoint_writer_authority"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        import entrypoint_writer_authority as mod  # type: ignore[import]
    return mod


def _build_authority(*, instance_id: str = "test-instance", client: Any):
    """Return a fresh EntrypointWriterAuthority with patched Redis & identity."""
    mod = _fresh_authority_module()

    auth = mod.EntrypointWriterAuthority()
    # Patch at the instance level via closure
    auth._patched_client = client  # type: ignore[attr-defined]

    # Monkey-patch module-level helpers on the class instance
    # (we wrap acquire_once to inject the fake client)
    original_acquire_once = auth.acquire_once.__func__  # type: ignore[attr-defined]

    connect_patch = _make_connect_redis_patch(client)
    identity_patch = _make_instance_identity_patch(instance_id)

    # We patch the module-level functions used inside the class methods
    setattr(mod, "_connect_redis", connect_patch)
    setattr(mod, "_instance_identity", identity_patch)
    return auth, mod


def _write_stale_metadata(
    client: Any,
    meta_key: str,
    lock_value: str,
    age_seconds: float = 300.0,
) -> None:
    """Write metadata that simulates a holder whose heartbeat is *age_seconds* old."""
    payload = json.dumps(
        {
            "token": lock_value.split(":")[0],
            "instance_id": "stale-instance",
            "generation": 1,
            "acquired_at": time.time() - age_seconds,
            "heartbeat_at": time.time() - age_seconds,
            "lock_ttl_s": 60,
            "source": "test",
        }
    )
    client.set(meta_key, payload, ex=3600)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestNormalStartup(unittest.TestCase):
    """Single instance should acquire the lock and log LOCK_ACQUIRED."""

    def test_acquires_lock_on_empty_redis(self):
        import fakeredis

        server = fakeredis.FakeServer()
        client = _make_fake_redis(server)
        auth, mod = _build_authority(instance_id="inst-A", client=client)

        shutdown = threading.Event()
        # Use a short standby limit so the test doesn't hang
        with patch.dict(os.environ, {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "5",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "5",
            "NIJA_WRITER_LOCK_KEY": "nija:writer_lock:test",
            "NIJA_WRITER_LOCK_META_KEY": "nija:writer_lock_meta:test",
            "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:test",
            "NIJA_LEASE_GENERATION_KEY": "nija:lease:generation:test",
            "NIJA_WRITER_LOCK_SCOPE": "test",
            "NIJA_WRITER_LOCK_TTL_S": "60",
        }):
            result = auth.acquire_with_standby(shutdown_event=shutdown)

        self.assertTrue(result.acquired, f"Expected acquired=True, error={result.error}")
        self.assertGreater(int(result.token), 0, "Fencing token should be a positive integer")
        self.assertGreater(result.generation, 0, "Generation counter should be > 0")
        self.assertFalse(result.local_fallback, "Should not fall back to local mode")

        # The lock should actually be present in Redis
        lock_val = client.get("nija:writer_lock:test")
        self.assertIsNotNone(lock_val, "Lock key should exist in Redis after acquisition")
        self.assertIn(result.token, lock_val)

        # Heartbeat thread should be running
        hb_threads = [t for t in threading.enumerate() if "heartbeat" in t.name.lower()]
        self.assertTrue(any(t.is_alive() for t in hb_threads), "Heartbeat thread should be alive")

        auth.release()

    def test_scan_started_recorded(self):
        """record_scan_started() should update the timestamp and log the event."""
        import fakeredis

        server = fakeredis.FakeServer()
        client = _make_fake_redis(server)
        auth, _ = _build_authority(instance_id="inst-scan", client=client)

        with patch.dict(os.environ, {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "5",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "5",
            "NIJA_WRITER_LOCK_KEY": "nija:writer_lock:test-scan",
            "NIJA_WRITER_LOCK_META_KEY": "nija:writer_lock_meta:test-scan",
            "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:test-scan",
            "NIJA_LEASE_GENERATION_KEY": "nija:lease:generation:test-scan",
            "NIJA_WRITER_LOCK_SCOPE": "test-scan",
            "NIJA_WRITER_LOCK_TTL_S": "60",
        }):
            result = auth.acquire_with_standby()

        self.assertTrue(result.acquired)
        self.assertEqual(auth._scan_started_at, 0.0, "scan_started_at should be 0 before record")
        before = time.time()
        auth.record_scan_started()
        self.assertGreater(auth._scan_started_at, 0.0)
        self.assertGreaterEqual(auth._scan_started_at, before)

        # Calling again should be idempotent
        first_ts = auth._scan_started_at
        time.sleep(0.01)
        auth.record_scan_started()
        self.assertEqual(auth._scan_started_at, first_ts, "Second call must not update timestamp")

        auth.release()


class TestGracefulFailover(unittest.TestCase):
    """After the first writer releases, the second should acquire immediately."""

    def test_second_instance_acquires_after_graceful_release(self):
        import fakeredis

        server = fakeredis.FakeServer()
        client_a = _make_fake_redis(server)
        client_b = _make_fake_redis(server)

        auth_a, mod_a = _build_authority(instance_id="inst-A", client=client_a)
        lock_key = "nija:writer_lock:failover"
        meta_key = "nija:writer_lock_meta:failover"
        env = {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "5",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "5",
            "NIJA_WRITER_LOCK_KEY": lock_key,
            "NIJA_WRITER_LOCK_META_KEY": meta_key,
            "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:failover",
            "NIJA_LEASE_GENERATION_KEY": "nija:lease:generation:failover",
            "NIJA_WRITER_LOCK_SCOPE": "failover",
            "NIJA_WRITER_LOCK_TTL_S": "60",
        }

        with patch.dict(os.environ, env):
            result_a = auth_a.acquire_with_standby()
        self.assertTrue(result_a.acquired, f"Instance A should acquire, error={result_a.error}")
        gen_a = result_a.generation

        # Instance A releases gracefully
        auth_a.release()
        self.assertIsNone(client_a.get(lock_key), "Lock should be gone after release")

        # Instance B should now acquire immediately
        auth_b, mod_b = _build_authority(instance_id="inst-B", client=client_b)
        with patch.dict(os.environ, env):
            result_b = auth_b.acquire_with_standby()

        self.assertTrue(result_b.acquired, f"Instance B should acquire after A releases, error={result_b.error}")
        self.assertGreater(result_b.generation, gen_a, "Generation must increase after failover")

        lock_val = client_b.get(lock_key)
        self.assertIsNotNone(lock_val)
        self.assertIn(result_b.token, lock_val)

        auth_b.release()


class TestStaleLockRecovery(unittest.TestCase):
    """When the lock holder's heartbeat is stale, a new instance should reclaim it."""

    def test_stale_lock_is_reclaimed(self):
        import fakeredis

        server = fakeredis.FakeServer()
        client = _make_fake_redis(server)

        lock_key = "nija:writer_lock:stale"
        meta_key = "nija:writer_lock_meta:stale"
        fencing_key = "nija:writer_fence:stale"
        gen_key = "nija:lease:generation:stale"

        # Manually plant a "stale" lock as if a crashed instance held it
        stale_holder = "99:instance=crashed-instance|pid=999"
        client.set(lock_key, stale_holder, ex=3600)
        _write_stale_metadata(client, meta_key, stale_holder, age_seconds=300)

        auth, _ = _build_authority(instance_id="inst-recovery", client=client)
        env = {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "10",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "10",
            "NIJA_ENTRYPOINT_WRITER_LOCK_RETRY_S": "0.1",
            "NIJA_WRITER_LOCK_KEY": lock_key,
            "NIJA_WRITER_LOCK_META_KEY": meta_key,
            "NIJA_WRITER_FENCING_KEY": fencing_key,
            "NIJA_LEASE_GENERATION_KEY": gen_key,
            "NIJA_WRITER_LOCK_SCOPE": "stale",
            "NIJA_WRITER_LOCK_TTL_S": "60",
            # 30-second threshold so 300-second-old heartbeat is definitely stale
            "NIJA_WRITER_STALE_LOCK_THRESHOLD_S": "30",
        }

        with patch.dict(os.environ, env):
            result = auth.acquire_with_standby()

        self.assertTrue(result.acquired, f"Should reclaim stale lock, error={result.error}")
        self.assertNotEqual(result.instance_id, "crashed-instance")
        self.assertEqual(result.instance_id, "inst-recovery")

        # The new lock value should belong to inst-recovery, not crashed-instance
        lock_val = client.get(lock_key)
        self.assertIsNotNone(lock_val)
        self.assertNotIn("crashed-instance", lock_val)
        self.assertIn(result.token, lock_val)

        auth.release()

    def test_fresh_lock_is_not_reclaimed(self):
        """A lock with a fresh heartbeat must never be forcibly evicted."""
        import fakeredis

        server = fakeredis.FakeServer()
        client = _make_fake_redis(server)

        lock_key = "nija:writer_lock:fresh"
        meta_key = "nija:writer_lock_meta:fresh"

        # Plant a lock whose heartbeat is only 5 seconds old (very fresh)
        live_holder = "1:instance=live-instance|pid=100"
        client.set(lock_key, live_holder, ex=3600)
        _write_stale_metadata(client, meta_key, live_holder, age_seconds=5)

        auth, _ = _build_authority(instance_id="inst-challenger", client=client)
        env = {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "2",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "2",
            "NIJA_ENTRYPOINT_WRITER_LOCK_RETRY_S": "0.1",
            "NIJA_WRITER_LOCK_KEY": lock_key,
            "NIJA_WRITER_LOCK_META_KEY": meta_key,
            "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:fresh",
            "NIJA_LEASE_GENERATION_KEY": "nija:lease:generation:fresh",
            "NIJA_WRITER_LOCK_SCOPE": "fresh",
            "NIJA_WRITER_LOCK_TTL_S": "60",
            # 30-second threshold — 5-second-old heartbeat is NOT stale
            "NIJA_WRITER_STALE_LOCK_THRESHOLD_S": "30",
        }

        with patch.dict(os.environ, env):
            result = auth.acquire_with_standby()

        self.assertFalse(result.acquired, "Fresh lock must NOT be reclaimed")
        self.assertEqual(result.error, "active_writer_lock_held")

        # Original lock must still be in place
        self.assertEqual(client.get(lock_key), live_holder)

    def test_dead_writer_is_reelected_after_stale_timeout(self):
        """If a writer dies without release, the next instance auto-reelects."""
        import fakeredis

        server = fakeredis.FakeServer()
        client_a = _make_fake_redis(server)
        client_b = _make_fake_redis(server)

        lock_key = "nija:writer_lock:dead-writer"
        meta_key = "nija:writer_lock_meta:dead-writer"
        env = {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "5",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "5",
            "NIJA_ENTRYPOINT_WRITER_LOCK_RETRY_S": "0.1",
            "NIJA_WRITER_LOCK_KEY": lock_key,
            "NIJA_WRITER_LOCK_META_KEY": meta_key,
            "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:dead-writer",
            "NIJA_LEASE_GENERATION_KEY": "nija:lease:generation:dead-writer",
            "NIJA_WRITER_LOCK_SCOPE": "dead-writer",
            "NIJA_WRITER_LOCK_TTL_S": "60",
            "NIJA_WRITER_STALE_LOCK_THRESHOLD_S": "30",
        }

        auth_a, _ = _build_authority(instance_id="inst-dead-A", client=client_a)
        with patch.dict(os.environ, env):
            result_a = auth_a.acquire_with_standby()
        self.assertTrue(result_a.acquired, f"Instance A should acquire first, error={result_a.error}")

        # Simulate a crashed writer: heartbeat stops and lock remains in Redis.
        auth_a._stop.set()
        heartbeat = getattr(auth_a, "_heartbeat_thread", None)
        if heartbeat is not None and heartbeat.is_alive():
            heartbeat.join(timeout=1.0)

        stale_holder = str(client_a.get(lock_key) or "")
        self.assertTrue(stale_holder, "Dead writer lock should still exist before failover")
        _write_stale_metadata(client_a, meta_key, stale_holder, age_seconds=120.0)

        auth_b, _ = _build_authority(instance_id="inst-recovery-B", client=client_b)
        with patch.dict(os.environ, env):
            result_b = auth_b.acquire_with_standby()

        self.assertTrue(
            result_b.acquired,
            f"Instance B should auto-reelect after stale timeout, error={result_b.error}",
        )
        self.assertEqual(result_b.instance_id, "inst-recovery-B")
        self.assertNotIn("inst-dead-A", str(client_b.get(lock_key) or ""))

        auth_b.release()


class TestSplitBrainPrevention(unittest.TestCase):
    """Two concurrent instances can never both hold the writer lock."""

    def test_concurrent_acquire_only_one_wins(self):
        """Race multiple instances simultaneously; exactly one must win."""
        import fakeredis

        server = fakeredis.FakeServer()

        winners: list[str] = []
        results_lock = threading.Lock()

        lock_key = "nija:writer_lock:race"
        meta_key = "nija:writer_lock_meta:race"
        env = {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "5",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "5",
            "NIJA_ENTRYPOINT_WRITER_LOCK_RETRY_S": "0.05",
            "NIJA_WRITER_LOCK_KEY": lock_key,
            "NIJA_WRITER_LOCK_META_KEY": meta_key,
            "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:race",
            "NIJA_LEASE_GENERATION_KEY": "nija:lease:generation:race",
            "NIJA_WRITER_LOCK_SCOPE": "race",
            "NIJA_WRITER_LOCK_TTL_S": "60",
        }

        try:
            import bot.entrypoint_writer_authority as _mod
        except ImportError:
            import entrypoint_writer_authority as _mod  # type: ignore[import]

        # Thread-local storage for per-thread instance identity — this lets us
        # patch _instance_identity once (safely) rather than re-patching from
        # every racing thread.
        _tl = threading.local()

        def _tl_identity():
            inst = getattr(_tl, "instance_id", "default")
            identity = {"instance_id": inst}
            return identity, f"instance={inst}|pid=1", inst

        acquired_auths: list[Any] = []
        start_barrier = threading.Barrier(5)

        def _race(instance_id: str, client: Any) -> None:
            _tl.instance_id = instance_id
            try:
                auth = _mod.EntrypointWriterAuthority()
                start_barrier.wait(timeout=5)  # release all threads together
                with patch.dict(os.environ, env):
                    result = auth.acquire_with_standby()
                if result.acquired:
                    with results_lock:
                        winners.append(instance_id)
                        acquired_auths.append(auth)
            except Exception as exc:
                # Don't fail the test on non-critical errors; just note them
                pass

        # Apply module patches once before spawning threads
        orig_connect = _mod._connect_redis
        orig_identity = _mod._instance_identity

        shared_client = _make_fake_redis(server)
        _mod._connect_redis = _make_connect_redis_patch(shared_client)
        _mod._instance_identity = _tl_identity

        try:
            clients = [_make_fake_redis(server) for _ in range(5)]
            threads = [
                threading.Thread(
                    target=_race, args=(f"racer-{i}", clients[i]), daemon=True
                )
                for i in range(5)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
        finally:
            _mod._connect_redis = orig_connect
            _mod._instance_identity = orig_identity

        self.assertEqual(
            len(winners),
            1,
            f"Exactly one winner expected, got {len(winners)}: {winners}",
        )

        # The lock in Redis must belong to the single winner
        client_verify = _make_fake_redis(server)
        lock_val = client_verify.get(lock_key)
        self.assertIsNotNone(lock_val, "Lock must still be held by the winner")

        for auth in acquired_auths:
            auth.release()

    def test_second_acquire_blocked_while_first_alive(self):
        """A second acquire attempt must fail (not block indefinitely) while first holds."""
        import fakeredis

        server = fakeredis.FakeServer()
        client_a = _make_fake_redis(server)
        client_b = _make_fake_redis(server)

        lock_key = "nija:writer_lock:block"
        meta_key = "nija:writer_lock_meta:block"
        env = {
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S": "2",
            "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "2",
            "NIJA_ENTRYPOINT_WRITER_LOCK_RETRY_S": "0.1",
            "NIJA_WRITER_LOCK_KEY": lock_key,
            "NIJA_WRITER_LOCK_META_KEY": meta_key,
            "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:block",
            "NIJA_LEASE_GENERATION_KEY": "nija:lease:generation:block",
            "NIJA_WRITER_LOCK_SCOPE": "block",
            "NIJA_WRITER_LOCK_TTL_S": "60",
            # Use a large stale threshold so the fresh lock is never reclaimed
            "NIJA_WRITER_STALE_LOCK_THRESHOLD_S": "600",
        }

        auth_a, _ = _build_authority(instance_id="inst-A", client=client_a)
        with patch.dict(os.environ, env):
            result_a = auth_a.acquire_with_standby()
        self.assertTrue(result_a.acquired)

        # Now instance B tries — it must be blocked, not acquire
        auth_b, _ = _build_authority(instance_id="inst-B", client=client_b)
        with patch.dict(os.environ, env):
            result_b = auth_b.acquire_with_standby()

        self.assertFalse(result_b.acquired, "Instance B must not acquire while A is live")
        self.assertEqual(result_b.error, "active_writer_lock_held")

        # Both must never both report acquired=True simultaneously
        self.assertFalse(
            auth_a.acquired and auth_b.acquired,
            "Split-brain: both instances report acquired=True",
        )

        auth_a.release()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
