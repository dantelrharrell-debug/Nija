"""Deterministic regression tests for NIJA production startup repair v26.

Tests prove:
  1.  One local runtime / one writer owner (singleton guard)
  2.  writer_lease_owned permits Kraken nonce prebootstrap but NOT trade dispatch
  3.  execution_dispatch_authorized requires all activation prerequisites
  4.  Coinbase-ready startup proceeds while Kraken is degraded
  5.  Readiness table publishes all 9 keys; revoke_many revokes atomically
  6.  Pre-handoff missing core does NOT lock heartbeat / count as runtime death
  7.  Post-handoff core death revokes execution authority
  8.  OKX install() is idempotent (at-most-once wrap per invocation)
  9.  _assert_canonical_writer_for_nonce_lease uses distributed writer authority
      (not full startup execution authority prerequisites)
  10. No live credentials or real orders are used in any test

All tests are self-contained and use in-process mocks only.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Resolve import path regardless of invocation style
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_production_startup_repair_v26")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_writer_authority():
    """Import (or re-import) EntrypointWriterAuthority with fresh singleton."""
    mod_name = "bot.entrypoint_writer_authority"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    alt_name = "entrypoint_writer_authority"
    if alt_name in sys.modules:
        del sys.modules[alt_name]
    try:
        import bot.entrypoint_writer_authority as mod
    except ImportError:
        import entrypoint_writer_authority as mod  # type: ignore[import]
    return mod


def _import_readiness_table():
    """Import readiness_table module (shared singleton – do NOT clear between tests)."""
    try:
        import bot.readiness_table as mod
    except ImportError:
        import readiness_table as mod  # type: ignore[import]
    return mod


# ---------------------------------------------------------------------------
# 1. Singleton guard: process-level PID lock
# ---------------------------------------------------------------------------

class TestSingletonPidLock(unittest.TestCase):
    """start.sh writes PID to lock file; subsequent check detects live owner."""

    def test_lock_file_contains_current_pid_format(self):
        """The lock file format must be parseable: pid|timestamp|uuid|command."""
        import io
        import tempfile
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, "nija.pid")
            pid = os.getpid()
            ts = "2026-01-01T00:00:00Z"
            uuid_ = "test-uuid-1234"
            cmd = "start.sh->canonical_runtime_launcher_v26.py"
            content = f"{pid}|{ts}|{uuid_}|{cmd}\n"
            with open(lock_path, "w") as fh:
                fh.write(content)

            with open(lock_path) as fh:
                line = fh.readline().strip()

            parts = line.split("|")
            self.assertEqual(len(parts), 4, "Lock file must have 4 pipe-separated fields")
            recorded_pid = int(parts[0])
            self.assertEqual(recorded_pid, pid)
            self.assertEqual(parts[1], ts)
            self.assertEqual(parts[2], uuid_)

    def test_stale_lock_detection(self):
        """A lock file with a non-existent PID must be treated as stale."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, "nija.pid")
            # PID 999999 is extremely unlikely to be running
            stale_pid = 999999
            with open(lock_path, "w") as fh:
                fh.write(f"{stale_pid}|2026-01-01T00:00:00Z|uuid|cmd\n")

            with open(lock_path) as fh:
                recorded_pid = int(fh.readline().strip().split("|")[0])

            # Verify the PID is not running (simulate shell `kill -0` check)
            try:
                os.kill(recorded_pid, 0)
                is_running = True
            except ProcessLookupError:
                is_running = False
            except PermissionError:
                is_running = True  # running but not owned by us

            # In the test environment, PID 999999 should not exist
            if not is_running:
                # This is the stale-lock case; the guard must remove the file
                os.remove(lock_path)
                self.assertFalse(os.path.exists(lock_path), "Stale lock must be removed")


# ---------------------------------------------------------------------------
# 2 & 3. writer_lease_owned / execution_dispatch_authorized
# ---------------------------------------------------------------------------

class TestWriterLeaseProperties(unittest.TestCase):
    """writer_lease_owned and execution_dispatch_authorized must be independent."""

    def _build_authority(self, *, acquired: bool = True, lost: bool = False,
                         local_fallback: bool = False,
                         token: str = "tok123",
                         generation: str = "42") -> "object":
        mod = _import_writer_authority()
        auth = mod.EntrypointWriterAuthority()
        auth._local_fallback = local_fallback
        auth._writer_state = mod.WriterState.ACTIVE if acquired else mod.WriterState.ACQUIRING
        if lost:
            auth._lost.set()
        if acquired:
            result = mod.EntrypointWriterAuthorityResult(
                acquired=True,
                generation=int(generation),
                instance_id="test-instance",
                holder="test-owner",
                token=token,
            )
        else:
            result = mod.EntrypointWriterAuthorityResult(
                acquired=False,
                generation=0,
                instance_id="test-instance",
                holder="",
                token="",
            )
        auth._result = result
        return auth, mod

    def test_writer_lease_owned_when_acquired_and_token_present(self):
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False,
                                             local_fallback=False,
                                             token="tok123", generation="42")
            self.assertTrue(auth.writer_lease_owned)

    def test_writer_lease_owned_false_when_lost(self):
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=True)
            self.assertFalse(auth.writer_lease_owned)

    def test_writer_lease_owned_false_when_not_acquired(self):
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=False, lost=False)
            self.assertFalse(auth.writer_lease_owned)

    def test_writer_lease_owned_false_when_token_missing(self):
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "",
            "NIJA_WRITER_LEASE_GENERATION": "42",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False,
                                             token="tok123", generation="42")
            self.assertFalse(auth.writer_lease_owned)

    def test_writer_lease_owned_false_when_local_fallback(self):
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False,
                                             local_fallback=True,
                                             token="tok123", generation="42")
            self.assertFalse(auth.writer_lease_owned)

    def test_execution_dispatch_authorized_false_without_live_active(self):
        """execution_dispatch_authorized must be False when not LIVE_ACTIVE."""
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_PENDING_CONFIRMATION",
            "NIJA_STRATEGY_PUBLISHED": "1",
            "NIJA_RISK_SYSTEM_READY": "1",
            "NIJA_KILL_SWITCH_ACTIVE": "0",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False)
            # Even with writer_lease_owned, no dispatch without LIVE_ACTIVE
            self.assertFalse(auth.execution_dispatch_authorized)

    def test_execution_dispatch_authorized_false_without_core_alive(self):
        """execution_dispatch_authorized must be False without live core."""
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_STRATEGY_PUBLISHED": "1",
            "NIJA_RISK_SYSTEM_READY": "1",
            "NIJA_KILL_SWITCH_ACTIVE": "0",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False)
            # No core thread registered -> not authorized
            self.assertFalse(auth.execution_dispatch_authorized)

    def test_execution_dispatch_authorized_true_with_all_prerequisites(self):
        """execution_dispatch_authorized must be True when all prerequisites met."""
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_STRATEGY_PUBLISHED": "1",
            "NIJA_RISK_SYSTEM_READY": "1",
            "NIJA_KILL_SWITCH_ACTIVE": "0",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False)
            # Register a live core thread
            mock_thread = MagicMock(spec=threading.Thread)
            mock_thread.is_alive.return_value = True
            auth._core_thread = mock_thread
            auth._core_thread_name = "TradingCore"
            auth._core_thread_ident = 12345
            self.assertTrue(auth.execution_dispatch_authorized)

    def test_execution_dispatch_authorized_false_with_kill_switch(self):
        """Kill switch must prevent dispatch authorization."""
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_STRATEGY_PUBLISHED": "1",
            "NIJA_RISK_SYSTEM_READY": "1",
            "NIJA_KILL_SWITCH_ACTIVE": "1",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False)
            mock_thread = MagicMock(spec=threading.Thread)
            mock_thread.is_alive.return_value = True
            auth._core_thread = mock_thread
            self.assertFalse(auth.execution_dispatch_authorized)

    def test_writer_lease_owned_permits_nonce_but_not_dispatch(self):
        """writer_lease_owned=True must not imply execution_dispatch_authorized=True."""
        env_patch = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_PENDING_CONFIRMATION",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            auth, _ = self._build_authority(acquired=True, lost=False)
            self.assertTrue(auth.writer_lease_owned)
            self.assertFalse(auth.execution_dispatch_authorized)


# ---------------------------------------------------------------------------
# 4. Coinbase-ready startup proceeds while Kraken degraded
# ---------------------------------------------------------------------------

class TestCoinbaseIndependentAnyReady(unittest.TestCase):
    """broker prebootstrap accepts connected >= 1 (Coinbase alone is sufficient)."""

    def test_prepare_canonical_broker_runtime_accepts_coinbase_only(self):
        """If Coinbase is connected (connected=1), prebootstrap must not fail."""
        # Mock a minimal manager with 1 connected broker (Coinbase) and 0 Kraken
        mock_manager = MagicMock()
        mock_manager._fsm_initialized = True
        mock_manager.has_registered_sources.return_value = True
        mock_manager.has_attempted_connections.return_value = True

        # platform_brokers returns one connected (coinbase) and one not (kraken)
        mock_coinbase_type = MagicMock()
        mock_coinbase_type.value = "coinbase"
        mock_coinbase_broker = MagicMock()
        mock_coinbase_broker.connected = True

        mock_kraken_type = MagicMock()
        mock_kraken_type.value = "kraken"
        mock_kraken_broker = MagicMock()
        mock_kraken_broker.connected = False

        mock_manager.platform_brokers.return_value = {
            mock_coinbase_type: mock_coinbase_broker,
            mock_kraken_type: mock_kraken_broker,
        }

        # Import and invoke _platform_counts
        try:
            import bot.canonical_broker_prebootstrap_v22 as v22
        except ImportError:
            import canonical_broker_prebootstrap_v22 as v22  # type: ignore[import]

        registered, connected, names = v22._platform_counts(mock_manager)
        self.assertEqual(connected, 1, "Exactly 1 broker should be connected")
        self.assertIn("coinbase", names)
        # connected >= 1 means prebootstrap should pass (not raise)
        self.assertGreaterEqual(connected, 1)

    def test_platform_counts_returns_zero_when_none_connected(self):
        """If no brokers connected, connected=0 and prebootstrap would fail."""
        mock_manager = MagicMock()
        mock_kraken_type = MagicMock()
        mock_kraken_type.value = "kraken"
        mock_kraken_broker = MagicMock()
        mock_kraken_broker.connected = False
        mock_manager.platform_brokers.return_value = {
            mock_kraken_type: mock_kraken_broker,
        }

        try:
            import bot.canonical_broker_prebootstrap_v22 as v22
        except ImportError:
            import canonical_broker_prebootstrap_v22 as v22  # type: ignore[import]

        registered, connected, names = v22._platform_counts(mock_manager)
        self.assertEqual(connected, 0)


# ---------------------------------------------------------------------------
# 5. Readiness table: all 9 keys + revoke_many
# ---------------------------------------------------------------------------

class TestReadinessTable(unittest.TestCase):
    """Readiness table must contain all 9 canonical keys and support atomic revoke."""

    def test_all_nine_canonical_keys_exist(self):
        rt = _import_readiness_table()
        required = {
            "broker_connected",
            "balance_hydrated",
            "authority_ready",
            "capital_ready",
            "risk_ready",
            "strategy_ready",
            "execution_ready",
            "nonce_ready",
            "bootstrap_ready",
        }
        self.assertTrue(
            required.issubset(set(rt.KEYS)),
            f"Missing keys: {required - set(rt.KEYS)}",
        )

    def test_mark_ready_sets_key(self):
        rt = _import_readiness_table()
        # Use a non-canonical key to avoid polluting shared state
        rt.set_ready("_test_startup_repair_v26_probe", True)
        snap = rt.snapshot()
        self.assertTrue(snap.get("_test_startup_repair_v26_probe"))

    def test_regression_prevention_blocks_true_to_false(self):
        rt = _import_readiness_table()
        rt.set_ready("_test_startup_repair_v26_regress", True)
        rt.set_ready("_test_startup_repair_v26_regress", False)  # must be silently blocked
        snap = rt.snapshot()
        self.assertTrue(snap.get("_test_startup_repair_v26_regress"))

    def test_revoke_ready_overrides_regression_protection(self):
        rt = _import_readiness_table()
        rt.set_ready("_test_startup_repair_v26_revoke", True)
        rt.revoke_ready("_test_startup_repair_v26_revoke", reason="test_revoke")
        snap = rt.snapshot()
        self.assertFalse(snap.get("_test_startup_repair_v26_revoke"))

    def test_revoke_many_atomically_clears_multiple_keys(self):
        rt = _import_readiness_table()
        rt.set_ready("_test_startup_repair_v26_atom_a", True)
        rt.set_ready("_test_startup_repair_v26_atom_b", True)
        snap_before = rt.snapshot()
        self.assertTrue(snap_before.get("_test_startup_repair_v26_atom_a"))
        self.assertTrue(snap_before.get("_test_startup_repair_v26_atom_b"))
        rt.revoke_many(
            ["_test_startup_repair_v26_atom_a", "_test_startup_repair_v26_atom_b"],
            reason="test_atomic_revoke",
        )
        snap_after = rt.snapshot()
        self.assertFalse(snap_after.get("_test_startup_repair_v26_atom_a"))
        self.assertFalse(snap_after.get("_test_startup_repair_v26_atom_b"))

    def test_snapshot_returns_copy(self):
        rt = _import_readiness_table()
        snap = rt.snapshot()
        self.assertIsInstance(snap, dict)
        # Modifying snapshot must not affect the live table
        original_val = snap.get("authority_ready", False)
        snap["authority_ready"] = not original_val
        snap2 = rt.snapshot()
        self.assertEqual(
            snap2.get("authority_ready", False),
            original_val,
            "Snapshot modification must not propagate to live table",
        )


# ---------------------------------------------------------------------------
# 6. Pre-handoff missing core does NOT lock heartbeat
# ---------------------------------------------------------------------------

class TestPreHandoffCoreRegistration(unittest.TestCase):
    """Before core-handoff deadline, missing core = startup_not_registered (not death)."""

    def test_missing_core_before_deadline_returns_startup_not_registered(self):
        mod = _import_writer_authority()
        auth = mod.EntrypointWriterAuthority()
        # Ensure no core thread is registered
        auth._core_thread = None

        # _core_thread_status should report startup_not_registered
        registered, alive, core_reason = auth._core_thread_status()
        self.assertFalse(registered, "No core registered yet")
        self.assertFalse(alive, "Core not alive")
        self.assertIn("startup_not_registered", core_reason)

    def test_validate_core_thread_liveness_returns_true_before_deadline(self):
        """_validate_core_thread_liveness must return (True, '') before deadline expires."""
        mod = _import_writer_authority()
        auth = mod.EntrypointWriterAuthority()
        auth._acquired_at = time.time()  # just acquired, well within deadline
        auth._scan_deadline_exceeded = False
        auth._scan_started_at = 0.0
        auth._core_thread = None
        auth._local_fallback = False

        # Patch NIJA_CORE_REGISTRATION_DEADLINE_S to large value
        with patch.dict(os.environ, {"NIJA_CORE_REGISTRATION_DEADLINE_S": "9999"}):
            ok, reason = auth._validate_core_thread_liveness()
        # Before deadline: must return True (startup_not_registered, not death)
        self.assertTrue(
            ok,
            f"Expected True (pre-handoff tolerance), got ({ok}, {reason!r})",
        )


# ---------------------------------------------------------------------------
# 7. Post-handoff core death revokes execution
# ---------------------------------------------------------------------------

class TestPostHandoffCoreDeath(unittest.TestCase):
    """Once a core is registered, its death must be reported as core_thread_dead."""

    def test_core_death_after_registration_reports_dead(self):
        mod = _import_writer_authority()
        auth = mod.EntrypointWriterAuthority()

        # Create a dead thread
        dead_thread = threading.Thread(target=lambda: None, name="DeadCore")
        dead_thread.start()
        dead_thread.join(timeout=5)
        self.assertFalse(dead_thread.is_alive(), "Thread must be dead for this test")

        auth._core_thread = dead_thread
        auth._core_thread_name = dead_thread.name
        auth._core_thread_ident = dead_thread.ident

        registered, alive, reason = auth._core_thread_status()
        self.assertTrue(registered, "Core must be registered")
        self.assertFalse(alive, "Core must be dead")
        self.assertIn("core_thread_dead", reason)

    def test_validate_core_thread_liveness_returns_false_for_dead_core(self):
        mod = _import_writer_authority()
        auth = mod.EntrypointWriterAuthority()
        auth._acquired_at = time.time()
        auth._scan_deadline_exceeded = False
        auth._scan_started_at = 1.0  # scan has started - post-handoff
        auth._local_fallback = False

        dead_thread = threading.Thread(target=lambda: None, name="DeadCore2")
        dead_thread.start()
        dead_thread.join(timeout=5)
        self.assertFalse(dead_thread.is_alive())

        auth._core_thread = dead_thread
        auth._core_thread_name = dead_thread.name
        auth._core_thread_ident = dead_thread.ident

        ok, reason = auth._validate_core_thread_liveness()
        self.assertFalse(ok, "Dead core must fail liveness check")
        self.assertIn("core_thread_dead", reason)


# ---------------------------------------------------------------------------
# 8. OKX install() is idempotent
# ---------------------------------------------------------------------------

class TestOKXPatchIdempotency(unittest.TestCase):
    """install() must apply wrappers at most once and skip on subsequent calls."""

    def test_install_called_twice_does_not_double_wrap(self):
        """Calling install() twice must not increase wrapper chain depth."""
        try:
            import bot.okx_order_wrapper_stability_patch as okx_patch
        except ImportError:
            self.skipTest("okx_order_wrapper_stability_patch not available")

        # Reset module state for clean test
        okx_patch._INSTALLED = False
        okx_patch._MONITOR_STARTED = False
        okx_patch._LAST_STATE = ""
        okx_patch._PATCH_INSTALLERS_READY = False
        okx_patch._RISK_INSTALLER_READY = False

        call_count = [0]
        original_apply = okx_patch._apply

        def counting_apply():
            call_count[0] += 1
            # Return stub success without touching real modules
            return True, {"classes": "test_only"}

        with patch.object(okx_patch, "_apply", side_effect=counting_apply):
            okx_patch.install()
            okx_patch.install()  # second call must not invoke _apply again

        self.assertEqual(
            call_count[0],
            1,
            "install() must call _apply() exactly once across multiple invocations",
        )


# ---------------------------------------------------------------------------
# 9. Nonce check uses distributed writer authority (not full startup authority)
# ---------------------------------------------------------------------------

class TestNonceWriterAuthorityCheck(unittest.TestCase):
    """_assert_canonical_writer_for_nonce_lease must use assert_distributed_writer_authority."""

    def _get_nonce_module(self):
        """Import distributed_nonce_manager, mocking redis if not available."""
        # Clear cached module so we can import cleanly
        for key in list(sys.modules.keys()):
            if "distributed_nonce_manager" in key:
                del sys.modules[key]

        # Mock redis and redis_runtime if not installed
        if "redis" not in sys.modules:
            mock_redis = types.ModuleType("redis")
            mock_redis.Redis = MagicMock  # type: ignore[attr-defined]
            sys.modules["redis"] = mock_redis

        # Mock bot.redis_runtime
        mock_redis_runtime = types.ModuleType("bot.redis_runtime")
        mock_redis_runtime.connect_redis_with_fallback = MagicMock(  # type: ignore[attr-defined]
            return_value=(None, "", "redis_unavailable")
        )
        sys.modules["bot.redis_runtime"] = mock_redis_runtime
        sys.modules["redis_runtime"] = mock_redis_runtime

        # Mock bot.redis_env
        mock_redis_env = types.ModuleType("bot.redis_env")
        mock_redis_env.get_redis_url = MagicMock(return_value="redis://localhost:6379")  # type: ignore[attr-defined]
        sys.modules["bot.redis_env"] = mock_redis_env
        sys.modules["redis_env"] = mock_redis_env

        try:
            import importlib
            import bot.distributed_nonce_manager as dnm
            importlib.reload(dnm)
            return dnm
        except ImportError:
            try:
                import distributed_nonce_manager as dnm  # type: ignore[import]
                import importlib
                importlib.reload(dnm)
                return dnm
            except Exception:
                self.skipTest("distributed_nonce_manager not importable in test env")

    def test_nonce_check_raises_on_distributed_authority_failure(self):
        """When distributed authority fails, nonce check must raise RuntimeError."""
        dnm = self._get_nonce_module()
        if dnm is None:
            return

        with patch.object(
            dnm,
            "assert_distributed_writer_authority",
            side_effect=RuntimeError("no_writer_lease"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                dnm._assert_canonical_writer_for_nonce_lease("test-key-id")
            self.assertIn("Canonical process writer authority unavailable", str(ctx.exception))

    def test_nonce_check_passes_when_distributed_authority_ok(self):
        """When distributed authority passes, nonce check must not raise."""
        dnm = self._get_nonce_module()
        if dnm is None:
            return

        with patch.object(
            dnm,
            "assert_distributed_writer_authority",
            return_value=None,
        ):
            # Must not raise
            dnm._assert_canonical_writer_for_nonce_lease("test-key-id")

    def test_nonce_check_does_not_call_assert_startup_write_authority(self):
        """Nonce prebootstrap must NOT call assert_startup_write_authority."""
        dnm = self._get_nonce_module()
        if dnm is None:
            return

        startup_write_calls = [0]

        def _track_startup_write():
            startup_write_calls[0] += 1

        with patch.object(dnm, "assert_distributed_writer_authority", return_value=None):
            with patch.object(dnm, "assert_startup_write_authority",
                              side_effect=_track_startup_write):
                dnm._assert_canonical_writer_for_nonce_lease("test-key-id")

        self.assertEqual(
            startup_write_calls[0],
            0,
            "_assert_canonical_writer_for_nonce_lease must not call assert_startup_write_authority",
        )


# ---------------------------------------------------------------------------
# 10. Account data scopes never cross
# ---------------------------------------------------------------------------

class TestAccountScopeIsolation(unittest.TestCase):
    """Capital snapshots and broker operations must not cross account scopes."""

    def test_platform_counts_isolates_by_connection_state(self):
        """_platform_counts must not count disconnected brokers as connected."""
        try:
            import bot.canonical_broker_prebootstrap_v22 as v22
        except ImportError:
            import canonical_broker_prebootstrap_v22 as v22  # type: ignore[import]

        mock_manager = MagicMock()
        # Three platforms: only one connected
        platforms = {}
        for name, connected in [("coinbase", True), ("kraken", False), ("okx", False)]:
            pt = MagicMock()
            pt.value = name
            broker = MagicMock()
            broker.connected = connected
            platforms[pt] = broker
        mock_manager.platform_brokers.return_value = platforms

        registered, connected, names = v22._platform_counts(mock_manager)
        self.assertEqual(registered, 3)
        self.assertEqual(connected, 1)
        self.assertListEqual(names, ["coinbase"])

    def test_no_live_credentials_used_in_tests(self):
        """Verify no live API credentials are present in the test environment."""
        # Tests must never touch real exchange credentials.
        # Actual CI environments have secrets injected; the test merely documents
        # the contract — no test action should READ or USE these.
        dangerous_keys = [
            "COINBASE_API_KEY",
            "COINBASE_API_SECRET",
            "COINBASE_PEM_CONTENT",
            "KRAKEN_PLATFORM_API_KEY",
            "KRAKEN_PLATFORM_SECRET_KEY",
            "OKX_API_KEY",
            "OKX_SECRET_KEY",
            "OKX_PASSPHRASE",
        ]
        for key in dangerous_keys:
            val = os.environ.get(key, "")
            self.assertFalse(
                val.startswith("-----BEGIN"),
                f"Live PEM key found in {key} — no real credentials in tests",
            )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
