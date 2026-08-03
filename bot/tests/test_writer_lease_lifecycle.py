"""Regression tests for distributed writer lease lifecycle.

Covers the bugs fixed in the writer lease lifecycle overhaul:

1. Lease acquisition populates NIJA_WRITER_FENCING_TOKEN.
2. Fencing token is NOT cleared when the core thread has not been registered
   yet (startup phase) — only cleared when the registered thread dies.
3. Heartbeat startup: NIJA_WRITER_HEARTBEAT_ACTIVE is set after acquisition.
4. Core-thread death triggers re-election (lock released, token cleared).
5. Lease loss detected via NIJA_WRITER_LEASE_ACQUIRED=0 in heartbeat check.
6. Automatic writer re-election: second instance acquires after first's thread
   dies and lock is released.
7. Split-brain prevention: two concurrent instances can't both hold the lock.

All tests use ``unittest.mock`` so no live Redis or external services are
required.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Ensure bot package is importable from the repo root.
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Environment variable keys that must be cleaned up between tests.
# ---------------------------------------------------------------------------
_WRITER_ENV_KEYS = (
    "NIJA_WRITER_FENCING_TOKEN",
    "NIJA_WRITER_FENCING_TOKEN_FALLBACK",
    "NIJA_WRITER_OWNER_ID",
    "NIJA_WRITER_INSTANCE_ID",
    "NIJA_WRITER_LEASE_GENERATION",
    "NIJA_WRITER_LEASE_ACQUIRED",
    "NIJA_LOCK_ACQUIRED",
    "NIJA_WRITER_LOCK_KEY",
    "NIJA_WRITER_LOCK_META_KEY",
    "NIJA_WRITER_LOCK_SCOPE",
    "NIJA_WRITER_LOCK_TTL_S",
    "NIJA_WRITER_LOCK_ACQUIRED_AT",
    "NIJA_WRITER_HEARTBEAT_ACTIVE",
    "NIJA_WRITER_HEARTBEAT_LAST_TS",
    "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
    "NIJA_LEASE_GENERATION_KEY",
    "NIJA_LOCK_BYPASS_MODE",
    "LIVE_CAPITAL_VERIFIED",
    "DRY_RUN_MODE",
    "PAPER_MODE",
    "KRAKEN_PLATFORM_API_KEY",
    "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S",
    "NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_CONFIRM_BYPASS_RISKS",
    "NIJA_RUNTIME_EXECUTION_AUTHORITY",
    "NIJA_EXECUTION_ACTIVE",
)


def _make_acquire_result(token: int = 17, generation: int = 23):
    """Return the raw Lua-script return value for a successful lock acquisition."""
    return [token, f"{token}:owner", 60_000, generation]


def _make_held_result(holder: str = "9:other-instance", pttl_ms: int = 42_000):
    """Return the raw Lua-script return value for a lock held by another instance."""
    return [0, holder, pttl_ms, 8]


def _identity(instance_id: str = "test-inst-A"):
    return (
        {"instance_id": instance_id, "hostname": "host"},
        f"instance={instance_id}|pid=99",
        instance_id,
    )


class _Base(unittest.TestCase):
    """Common setup / teardown for writer lease lifecycle tests."""

    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in _WRITER_ENV_KEYS}
        for k in _WRITER_ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ["DRY_RUN_MODE"] = "false"
        os.environ["PAPER_MODE"] = "false"
        os.environ["KRAKEN_PLATFORM_API_KEY"] = "test-key"
        os.environ["NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S"] = "0"
        os.environ["NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S"] = "0.1"

    def tearDown(self) -> None:
        for k in _WRITER_ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def _make_runtime(self, instance_id: str = "test-inst-A"):
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority

        rt = EntrypointWriterAuthority()
        rt._state_lock  # ensure attribute exists (fresh instance)
        return rt

    def _acquire(
        self,
        runtime,
        instance_id: str = "test-inst-A",
        token: int = 17,
        generation: int = 23,
    ):
        client = MagicMock()
        client.eval.return_value = _make_acquire_result(token, generation)
        client.set.return_value = True
        with (
            patch(
                "bot.entrypoint_writer_authority._connect_redis",
                return_value=(client, "rediss://fake", ""),
            ),
            patch(
                "bot.entrypoint_writer_authority._instance_identity",
                return_value=_identity(instance_id),
            ),
            patch.object(runtime, "_start_heartbeat"),
            patch.object(runtime, "_start_scan_started_watchdog"),
        ):
            result = runtime.acquire_once()
        return result, client


# ---------------------------------------------------------------------------
# 1. Lease acquisition populates fencing token
# ---------------------------------------------------------------------------

class TestLeaseAcquisition(_Base):

    def test_fencing_token_set_after_acquisition(self):
        rt = self._make_runtime()
        result, _ = self._acquire(rt)

        self.assertTrue(result.acquired, f"expected acquired=True; got error={result.error!r}")
        self.assertEqual(result.token, "17")
        self.assertEqual(result.generation, 23)
        self.assertEqual(os.environ.get("NIJA_WRITER_FENCING_TOKEN"), "17",
                         "NIJA_WRITER_FENCING_TOKEN must be set immediately after acquisition")

    def test_lease_acquired_env_var_set(self):
        rt = self._make_runtime()
        self._acquire(rt)
        self.assertEqual(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"), "1")

    def test_lease_generation_env_var_set(self):
        rt = self._make_runtime()
        self._acquire(rt)
        self.assertEqual(os.environ.get("NIJA_WRITER_LEASE_GENERATION"), "23")

    def test_heartbeat_active_set_after_acquisition(self):
        rt = self._make_runtime()
        self._acquire(rt)
        self.assertEqual(os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE"), "1",
                         "NIJA_WRITER_HEARTBEAT_ACTIVE must be set to 1 immediately after acquisition")

    def test_redis_unavailable_returns_not_acquired(self):
        rt = self._make_runtime()
        with patch(
            "bot.entrypoint_writer_authority._connect_redis",
            return_value=(None, "", "redis_unavailable"),
        ):
            result = rt.acquire_once()
        self.assertFalse(result.acquired)
        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN", os.environ)

    def test_lock_held_by_another_returns_not_acquired(self):
        rt = self._make_runtime()
        client = MagicMock()
        client.eval.return_value = _make_held_result()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis",
                  return_value=(client, "rediss://fake", "")),
            patch("bot.entrypoint_writer_authority._instance_identity",
                  return_value=_identity()),
        ):
            result = rt.acquire_once()
        self.assertFalse(result.acquired)
        self.assertEqual(result.error, "active_writer_lock_held")
        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN", os.environ)


# ---------------------------------------------------------------------------
# 2. Fencing token NOT cleared when core thread not yet registered
# ---------------------------------------------------------------------------

class TestFencingTokenPreservation(_Base):

    def test_token_not_cleared_when_core_thread_none(self):
        """_validate_core_thread_liveness must return True when no thread registered."""
        rt = self._make_runtime()
        self._acquire(rt)

        token_before = os.environ.get("NIJA_WRITER_FENCING_TOKEN")
        self.assertEqual(token_before, "17")

        # Simulate heartbeat ticks without a registered core thread.
        for _ in range(20):
            ok, reason = rt._validate_core_thread_liveness()
            self.assertTrue(ok,
                f"_validate_core_thread_liveness should return True when core thread is None; got ({ok!r}, {reason!r})")

        token_after = os.environ.get("NIJA_WRITER_FENCING_TOKEN")
        self.assertEqual(token_before, token_after,
                         "NIJA_WRITER_FENCING_TOKEN must not be cleared when core thread is None")

    def test_token_still_set_after_long_startup_delay(self):
        """Token must survive past what was previously the grace period (120 s)."""
        rt = self._make_runtime()
        self._acquire(rt)

        # Force acquired_at to 200 seconds ago — this used to trigger re-election.
        rt._acquired_at = time.time() - 200.0
        # _core_thread is None — still in startup phase.

        ok, reason = rt._validate_core_thread_liveness()
        self.assertTrue(ok, f"Expected True; got ({ok!r}, {reason!r})")
        self.assertIn("NIJA_WRITER_FENCING_TOKEN", os.environ,
                      "NIJA_WRITER_FENCING_TOKEN must still be present after 200 s with no core thread")


# ---------------------------------------------------------------------------
# 3. Heartbeat startup
# ---------------------------------------------------------------------------

class TestHeartbeatStartup(_Base):

    def test_heartbeat_thread_launched_after_acquisition(self):
        """_start_heartbeat must be called as part of _activate_distributed_authority."""
        rt = self._make_runtime()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis",
                  return_value=(MagicMock(eval=MagicMock(return_value=_make_acquire_result())),
                                "rediss://fake", "")),
            patch("bot.entrypoint_writer_authority._instance_identity",
                  return_value=_identity()),
            patch.object(rt, "_start_heartbeat") as mock_hb,
            patch.object(rt, "_start_scan_started_watchdog"),
        ):
            rt.acquire_once()

        mock_hb.assert_called_once()

    def test_heartbeat_timestamps_populated(self):
        rt = self._make_runtime()
        self._acquire(rt)

        last_ts = float(os.environ.get("NIJA_WRITER_HEARTBEAT_LAST_TS", "0"))
        alive_ts = float(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0"))
        self.assertGreater(last_ts, 0, "NIJA_WRITER_HEARTBEAT_LAST_TS should be a positive timestamp")
        self.assertGreater(alive_ts, 0, "NIJA_WRITER_HEARTBEAT_ALIVE_TS should be a positive timestamp")


# ---------------------------------------------------------------------------
# 4. Core-thread death triggers re-election
# ---------------------------------------------------------------------------

class TestCoreThreadDeathTriggerReelection(_Base):

    def _mock_seak(self):
        import sys
        mock_kernel = MagicMock()
        mock_kernel.get_seak.return_value = MagicMock()
        return patch.dict(sys.modules, {"bot.single_execution_authority_kernel": mock_kernel})

    def test_dead_registered_thread_returns_false(self):
        rt = self._make_runtime()
        self._acquire(rt)

        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join(timeout=2.0)

        rt._core_thread = dead_thread
        rt._core_thread_name = dead_thread.name
        rt._core_thread_started_at = time.time() - 5.0

        ok, reason = rt._validate_core_thread_liveness()
        self.assertFalse(ok, "Must return False when registered core thread is dead")
        self.assertIn("core_thread_dead", reason)

    def test_dead_core_thread_triggers_release_for_reelection(self):
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        client.eval.return_value = 1  # successful compare-and-delete

        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join(timeout=2.0)

        rt._core_thread = dead_thread
        rt._core_thread_name = dead_thread.name

        with patch.object(rt, "_mark_lost") as mock_lost:
            rt._release_owned_lock_for_reelection("core_thread_dead name=test")
            mock_lost.assert_called_once()
            args = mock_lost.call_args[0][0]
            self.assertIn("writer_lock_released_for_reelection", args)

    def test_fencing_token_cleared_after_core_thread_death(self):
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        token_before = os.environ.get("NIJA_WRITER_FENCING_TOKEN")
        self.assertIsNotNone(token_before)

        client.eval.return_value = 1
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join(timeout=2.0)
        rt._core_thread = dead_thread

        with self._mock_seak():
            rt._release_owned_lock_for_reelection("core_thread_dead")

        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN", os.environ,
                         "NIJA_WRITER_FENCING_TOKEN must be cleared after re-election")

    def test_lost_event_set_after_core_thread_death(self):
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        client.eval.return_value = 1
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join(timeout=2.0)
        rt._core_thread = dead_thread

        with self._mock_seak():
            rt._release_owned_lock_for_reelection("core_thread_dead")

        self.assertTrue(rt.lost, "runtime.lost must be True after core thread death")

    def test_heartbeat_tick_skips_renewal_when_core_dead(self):
        """_heartbeat_tick must release for re-election when core thread is dead."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        client.eval.return_value = 1  # compare-and-delete returns 1 (success)

        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join(timeout=2.0)

        rt._core_thread = dead_thread
        rt._core_thread_name = dead_thread.name

        with (
            patch.object(rt, "_release_owned_lock_for_reelection") as mock_reelect,
        ):
            ok, reason = rt._heartbeat_tick()

        self.assertFalse(ok)
        mock_reelect.assert_called_once()
        self.assertIn("core_thread_dead", reason)


# ---------------------------------------------------------------------------
# 5. Lease loss detection in authority heartbeat
# ---------------------------------------------------------------------------

class TestLeaseLossDetection(_Base):

    def test_check_authority_once_fails_when_lease_released(self):
        """_check_authority_once must fail when NIJA_WRITER_LEASE_ACQUIRED is explicitly 0."""
        import importlib
        # Reload to get a fresh module without cached state
        import sys
        ah_mod_name = "bot.authority_heartbeat"
        if ah_mod_name in sys.modules:
            ah = sys.modules[ah_mod_name]
        else:
            import bot.authority_heartbeat as ah  # noqa: F401

        os.environ["NIJA_WRITER_FENCING_TOKEN"] = "some-token"
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"

        from bot.authority_heartbeat import _check_authority_once

        ok, err = _check_authority_once(timeout_s=2.0)
        self.assertFalse(ok, "heartbeat check must fail when lease is explicitly released")
        self.assertIn("lease released", err.lower(),
                      f"Expected 'lease released' in error message; got: {err!r}")

    def test_check_authority_once_fails_when_fencing_token_missing(self):
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"

        from bot.authority_heartbeat import _check_authority_once

        ok, err = _check_authority_once(timeout_s=2.0)
        self.assertFalse(ok)
        self.assertIn("NIJA_WRITER_FENCING_TOKEN is not set", err)

    def _mock_seak(self):
        """Return a context manager that replaces the SEAK module with a mock."""
        import sys
        mock_kernel = MagicMock()
        mock_kernel.get_seak.return_value = MagicMock()
        return patch.dict(sys.modules, {"bot.single_execution_authority_kernel": mock_kernel})

    def test_on_lost_callback_invoked_when_lease_lost(self):
        rt = self._make_runtime()
        self._acquire(rt)

        received = []

        def _cb(reason: str) -> None:
            received.append(reason)

        rt.set_on_lost_callback(_cb)

        with self._mock_seak():
            rt._mark_lost("test_lease_lost")

        self.assertEqual(len(received), 1, "on_lost callback must be called exactly once")
        self.assertIn("test_lease_lost", received[0])

    def test_on_lost_callback_exception_does_not_propagate(self):
        rt = self._make_runtime()
        self._acquire(rt)

        def _bad_cb(reason: str) -> None:
            raise RuntimeError("callback error")

        rt.set_on_lost_callback(_bad_cb)

        # Must not raise even if callback raises.
        with self._mock_seak():
            try:
                rt._mark_lost("test_callback_error")
            except RuntimeError:
                self.fail("_mark_lost must not propagate exceptions from the callback")

    def test_mark_lost_clears_lease_acquired_env(self):
        rt = self._make_runtime()
        self._acquire(rt)

        self.assertEqual(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"), "1")

        with self._mock_seak():
            rt._mark_lost("test")

        self.assertEqual(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"), "0",
                         "NIJA_WRITER_LEASE_ACQUIRED must be 0 after _mark_lost()")

    def test_mark_lost_clears_fencing_token(self):
        rt = self._make_runtime()
        self._acquire(rt)

        self.assertIn("NIJA_WRITER_FENCING_TOKEN", os.environ)

        with self._mock_seak():
            rt._mark_lost("test")

        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN", os.environ)


# ---------------------------------------------------------------------------
# 6. Automatic writer re-election
# ---------------------------------------------------------------------------

class TestWriterReelection(_Base):

    def test_second_instance_acquires_after_first_releases(self):
        """After instance-A releases its lock, instance-B must acquire it."""
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority

        # Shared state across two "Redis client" mocks via a simple dict.
        store: dict[str, str] = {}

        def _eval(script, num_keys, *args):
            lock_key = args[0]
            fence_key = args[1]
            gen_key = args[2]
            owner = args[3]
            ttl = args[4]
            if lock_key in store:
                return [0, store[lock_key], 60_000, int(store.get(gen_key, "0"))]
            counter = int(store.get(fence_key, "0")) + 1
            gen = int(store.get(gen_key, "0")) + 1
            store[fence_key] = str(counter)
            store[gen_key] = str(gen)
            store[lock_key] = f"{counter}:{owner}"
            return [counter, store[lock_key], 60_000, gen]

        def _del(key):
            store.pop(key, None)
            return 1

        def _get(key):
            return store.get(key)

        client_A = MagicMock()
        client_A.eval.side_effect = _eval
        client_A.set.return_value = True
        client_A.get.side_effect = _get

        client_B = MagicMock()
        client_B.eval.side_effect = _eval
        client_B.set.return_value = True
        client_B.get.side_effect = _get

        rt_A = EntrypointWriterAuthority()
        rt_B = EntrypointWriterAuthority()

        with (
            patch("bot.entrypoint_writer_authority._connect_redis",
                  return_value=(client_A, "rediss://fake", "")),
            patch("bot.entrypoint_writer_authority._instance_identity",
                  return_value=_identity("inst-A")),
            patch.object(rt_A, "_start_heartbeat"),
            patch.object(rt_A, "_start_scan_started_watchdog"),
        ):
            res_A = rt_A.acquire_once()

        self.assertTrue(res_A.acquired, f"inst-A acquire failed: {res_A.error}")
        token_A = res_A.token

        # Simulate compare-and-delete for release.
        def _release_eval(script, num_keys, *args):
            lock_key = args[0]
            meta_key = args[1] if len(args) > 1 else ""
            expected = args[2] if len(args) > 2 else ""
            if store.get(lock_key) == expected:
                store.pop(lock_key, None)
                store.pop(meta_key, None)
                return 1
            return 0

        client_A.eval.side_effect = _release_eval
        rt_A.release()

        # Now inst-B should acquire.
        with (
            patch("bot.entrypoint_writer_authority._connect_redis",
                  return_value=(client_B, "rediss://fake", "")),
            patch("bot.entrypoint_writer_authority._instance_identity",
                  return_value=_identity("inst-B")),
            patch.object(rt_B, "_start_heartbeat"),
            patch.object(rt_B, "_start_scan_started_watchdog"),
        ):
            res_B = rt_B.acquire_once()

        self.assertTrue(res_B.acquired, f"inst-B acquire failed after inst-A released: {res_B.error}")
        self.assertNotEqual(res_B.token, token_A,
                            "inst-B must get a different fencing token than inst-A")
        rt_B.release()

    def test_stale_lock_is_reclaimed(self):
        """An instance with a stale metadata heartbeat is evicted and re-election occurs."""
        import json
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority

        store: dict[str, str] = {}

        lock_key = "nija:writer_lock:test"
        meta_key = "nija:writer_lock_meta:test"
        fence_key = "nija:writer_fence:test"
        gen_key = "nija:lease:generation:test"

        # Write a stale lock + metadata (heartbeat 600 s ago).
        stale_holder = "99:stale-instance"
        store[lock_key] = stale_holder
        store[meta_key] = json.dumps({
            "token": "99",
            "instance_id": "stale-inst",
            "generation": 1,
            "acquired_at": time.time() - 600,
            "heartbeat_at": time.time() - 600,
            "lock_ttl_s": 60,
            "source": "test",
        })
        store[fence_key] = "99"
        store[gen_key] = "1"

        def _eval(script, num_keys, *args):
            if "KEYS[1]" in script or len(args) >= 3:
                # Could be the acquire OR delete script.
                lock_k = args[0]
                if lock_k not in store:
                    # Acquire path.
                    fence_k = args[1]
                    g_k = args[2]
                    owner = args[3]
                    counter = int(store.get(fence_k, "0")) + 1
                    gen = int(store.get(g_k, "0")) + 1
                    store[fence_k] = str(counter)
                    store[g_k] = str(gen)
                    store[lock_k] = f"{counter}:{owner}"
                    return [counter, store[lock_k], 60_000, gen]
                else:
                    # Lock exists — return holder.
                    return [0, store[lock_k], 60_000, int(store.get(gen_key, "0"))]
            return 0

        def _delete_eval(script, num_keys, *args):
            # compare-and-delete for stale lock reclaim
            k = args[0]
            meta_k = args[1] if len(args) > 1 else ""
            expected = args[2] if len(args) > 2 else ""
            if not expected or store.get(k) == expected:
                store.pop(k, None)
                if meta_k:
                    store.pop(meta_k, None)
                return 1
            return 0

        # Sequence: first eval call returns stale lock; reclaim eval deletes it.
        # Then acquire eval succeeds.
        eval_calls: list = []

        def _smart_eval(script, num_keys, *args):
            if len(args) >= 4 and str(args[2]).startswith("nija:"):
                # Acquire script (4+ args, third arg is generation key).
                return _eval(script, num_keys, *args)
            else:
                # Delete / renew script.
                return _delete_eval(script, num_keys, *args)

        client = MagicMock()
        client.eval.side_effect = _smart_eval
        client.get.side_effect = lambda k: store.get(k)
        client.set.return_value = True

        rt = EntrypointWriterAuthority()

        env = {
            "NIJA_WRITER_LOCK_KEY": lock_key,
            "NIJA_WRITER_LOCK_META_KEY": meta_key,
            "NIJA_WRITER_FENCING_KEY": fence_key,
            "NIJA_LEASE_GENERATION_KEY": gen_key,
            "NIJA_WRITER_STALE_LOCK_THRESHOLD_S": "300",
        }
        with (
            patch.dict(os.environ, env),
            patch("bot.entrypoint_writer_authority._connect_redis",
                  return_value=(client, "rediss://fake", "")),
            patch("bot.entrypoint_writer_authority._instance_identity",
                  return_value=_identity("inst-new")),
            patch.object(rt, "_start_heartbeat"),
            patch.object(rt, "_start_scan_started_watchdog"),
        ):
            result = rt.acquire_once()

        # After stale eviction, the new instance must have acquired.
        self.assertTrue(result.acquired,
                        f"Expected new instance to acquire after stale lock eviction; error={result.error!r}")
        rt.release()


# ---------------------------------------------------------------------------
# 7. Split-brain prevention
# ---------------------------------------------------------------------------

class TestSplitBrainPrevention(_Base):

    def test_only_one_of_two_concurrent_instances_wins(self):
        """Two concurrent instances attempting acquisition must result in only one winner."""
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority

        store: dict[str, str] = {}
        store_lock = threading.Lock()

        def _atomic_eval(script, num_keys, *args):
            """Atomic lock acquisition: only the first SET NX wins."""
            with store_lock:
                lock_k = args[0]
                fence_k = args[1]
                gen_k = args[2]
                owner = args[3]
                if lock_k in store:
                    return [0, store[lock_k], 60_000, int(store.get(gen_k, "0"))]
                counter = int(store.get(fence_k, "0")) + 1
                gen = int(store.get(gen_k, "0")) + 1
                store[fence_k] = str(counter)
                store[gen_k] = str(gen)
                store[lock_k] = f"{counter}:{owner}"
                return [counter, store[lock_k], 60_000, gen]

        results = []

        def _try_acquire(instance_id: str) -> None:
            rt = EntrypointWriterAuthority()
            client = MagicMock()
            client.eval.side_effect = _atomic_eval
            client.set.return_value = True
            with (
                patch("bot.entrypoint_writer_authority._connect_redis",
                      return_value=(client, "rediss://fake", "")),
                patch("bot.entrypoint_writer_authority._instance_identity",
                      return_value=_identity(instance_id)),
                patch.object(rt, "_start_heartbeat"),
                patch.object(rt, "_start_scan_started_watchdog"),
            ):
                result = rt.acquire_once()
            results.append((instance_id, result.acquired, result.token))
            if result.acquired:
                client.eval.side_effect = lambda s, n, *a: 1  # compare-and-delete
                rt.release()

        threads = [
            threading.Thread(target=_try_acquire, args=(f"inst-{i}",))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        winners = [(inst, tok) for inst, ok, tok in results if ok]
        self.assertEqual(len(winners), 1,
                         f"Exactly one instance must win the lock; winners={winners!r}")

    def test_second_instance_cannot_acquire_while_first_alive(self):
        """When inst-A holds a healthy lock, inst-B must receive active_writer_lock_held."""
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority

        store: dict = {"nija:writer_lock:t": "42:inst-A"}

        def _held_eval(script, num_keys, *args):
            return [0, store.get(args[0], ""), 60_000, 1]

        rt_B = EntrypointWriterAuthority()
        client = MagicMock()
        client.eval.side_effect = _held_eval

        with (
            patch("bot.entrypoint_writer_authority._connect_redis",
                  return_value=(client, "rediss://fake", "")),
            patch("bot.entrypoint_writer_authority._instance_identity",
                  return_value=_identity("inst-B")),
            patch.dict(os.environ, {
                "NIJA_WRITER_LOCK_KEY": "nija:writer_lock:t",
                "NIJA_WRITER_LOCK_META_KEY": "",
                "NIJA_WRITER_FENCING_KEY": "nija:fence:t",
                "NIJA_LEASE_GENERATION_KEY": "nija:gen:t",
                "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S": "0",
            }),
        ):
            result = rt_B.acquire_once()

        self.assertFalse(result.acquired)
        self.assertEqual(result.error, "active_writer_lock_held")
        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN", os.environ,
                         "Inst-B must not set NIJA_WRITER_FENCING_TOKEN when lock is held by inst-A")


if __name__ == "__main__":
    unittest.main()
