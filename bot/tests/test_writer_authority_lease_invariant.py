"""Regression tests for writer authority lease lifecycle invariant (new fixes).

Covers:
  Fix 1  – normalize_derived_runtime_state() must NOT clear
            NIJA_WRITER_LEASE_ACQUIRED while the EntrypointWriterAuthority
            singleton actively holds the Redis lock.

  Fix 2  – authority_heartbeat._check_authority_once() must defer to the
            singleton's in-memory state before issuing its own Redis check.
            When the singleton reports acquired, the Redis round-trip is
            skipped entirely.

  Fix 3/4 – writer_generation_scope_repair_patch.get_redis_generation() now
             reads from NIJA_LEASE_GENERATION_KEY (default nija:lease:generation)
             instead of the per-key nonce lease key, preventing
             platform_lease_version_missing.

  Fix 6  – EntrypointWriterAuthority._check_authority_invariant() enforces:
            lease_acquired == (fencing_token_active AND heartbeat_running AND core_ok)
            If violated, the lease is released immediately.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make the bot package importable from repo root.
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Environment variable keys cleaned up between tests.
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
    "NIJA_RUNTIME_EXECUTION_AUTHORITY",
    "NIJA_RUNTIME_TRADING_STATE",
    "NIJA_CORE_THREAD_ALIVE",
    "NIJA_WRITER_RELEASE_IN_PROGRESS",
    "LIVE_CAPITAL_VERIFIED",
    "DRY_RUN_MODE",
    "PAPER_MODE",
    "KRAKEN_PLATFORM_API_KEY",
    "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S",
    "NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_CONFIRM_BYPASS_RISKS",
    "NIJA_EXECUTION_ACTIVE",
)


def _make_acquire_result(token: int = 42, generation: int = 99):
    return [token, f"{token}:owner", 60_000, generation]


def _identity(instance_id: str = "test-inst"):
    return (
        {"instance_id": instance_id, "hostname": "host"},
        f"instance={instance_id}|pid=99",
        instance_id,
    )


class _Base(unittest.TestCase):
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

    def _make_runtime(self):
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority
        return EntrypointWriterAuthority()

    def _acquire(self, runtime, token: int = 42, generation: int = 99):
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
                return_value=_identity(),
            ),
            patch.object(runtime, "_start_heartbeat"),
            patch.object(runtime, "_start_scan_started_watchdog"),
        ):
            result = runtime.acquire_once()
        return result, client

    @staticmethod
    def _mock_seak():
        mock_kernel = MagicMock()
        mock_kernel.get_seak.return_value = MagicMock()
        return patch.dict(sys.modules, {"bot.single_execution_authority_kernel": mock_kernel})


# ===========================================================================
# Fix 6: _check_authority_invariant
# ===========================================================================

class TestAuthorityInvariant(_Base):

    def test_invariant_ok_when_lease_and_token_both_set(self):
        """No violation when lease flag and fencing token are both present."""
        rt = self._make_runtime()
        self._acquire(rt)
        # After acquisition both flags are set.
        self.assertIn("NIJA_WRITER_FENCING_TOKEN", os.environ)
        self.assertEqual(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"), "1")

        ok, reason = rt._check_authority_invariant()

        self.assertTrue(ok, f"Invariant should pass but got reason={reason!r}")
        self.assertEqual(reason, "")

    def test_invariant_fires_when_lease_set_but_token_cleared(self):
        """VIOLATION: lease_acquired=1 but fencing token has been cleared."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)
        client.eval.return_value = 1  # Redis compare-and-delete succeeds.

        # Simulate external code popping the fencing token (e.g. _mark_lost
        # from another path) while NIJA_WRITER_LEASE_ACQUIRED was not cleared.
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        # Leave NIJA_WRITER_LEASE_ACQUIRED = "1"
        self.assertEqual(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"), "1")

        with self._mock_seak():
            ok, reason = rt._check_authority_invariant()

        self.assertFalse(ok, "Invariant must detect lease_acquired=1 but token missing")
        self.assertIn("fencing_token_missing", reason)
        # Authority must have been released.
        self.assertTrue(rt._stop.is_set(), "_stop must be set after invariant release")
        self.assertTrue(rt._lost.is_set(), "_lost must be set after invariant release")
        self.assertEqual(
            os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"),
            "0",
            "NIJA_WRITER_LEASE_ACQUIRED must be 0 after invariant release",
        )

    def test_invariant_fires_when_env_externally_cleared(self):
        """VIOLATION: singleton.acquired=True but env flag was externally reset to 0."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)
        client.eval.return_value = 1

        # Simulate render_startup_convergence_patch or similar resetting the flag.
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
        # Fencing token is still present (token not cleared by _mark_lost).
        self.assertIn("NIJA_WRITER_FENCING_TOKEN", os.environ)
        # Singleton still considers itself acquired.
        self.assertTrue(rt.acquired)

        with self._mock_seak():
            ok, reason = rt._check_authority_invariant()

        self.assertFalse(ok, "Invariant must detect singleton acquired but env cleared")
        self.assertIn("env_cleared", reason)
        self.assertTrue(rt._stop.is_set())
        self.assertTrue(rt._lost.is_set())

    def test_heartbeat_tick_calls_invariant_before_redis_renewal(self):
        """_heartbeat_tick must abort immediately when the invariant is violated."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)
        client.eval.return_value = 1

        # Clear fencing token to induce invariant violation.
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)

        with self._mock_seak():
            ok, reason = rt._heartbeat_tick()

        self.assertFalse(ok)
        self.assertIn("fencing_token_missing", reason)
        # Redis renewal Lua script must NOT have been called (invariant aborted).
        # The eval was called during _release_owned_lock_for_reelection compare-
        # and-delete, but NOT for the renewal eval that would have extended TTL.
        # Verify that NIJA_WRITER_HEARTBEAT_ACTIVE was not set to "1" (it would
        # only be set by the successful renewal branch).
        self.assertNotEqual(
            os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE"),
            "1",
            "NIJA_WRITER_HEARTBEAT_ACTIVE must not be set to 1 after invariant failure",
        )

    def test_invariant_ok_when_lease_not_set_during_startup(self):
        """No violation during pre-acquisition startup (both flags absent)."""
        rt = self._make_runtime()
        # Don't call _acquire — simulate pre-boot state.
        os.environ.pop("NIJA_WRITER_LEASE_ACQUIRED", None)
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)

        ok, reason = rt._check_authority_invariant()

        self.assertTrue(ok, "Startup grace: no violation when both flags absent")


# ===========================================================================
# Fix 1: normalize_derived_runtime_state must not clear the flag while
#         the singleton holds the lock.
# ===========================================================================

class TestNormalizeDerivedRuntimeState(_Base):

    def _run_normalize(self):
        from bot.render_startup_convergence_patch import normalize_derived_runtime_state
        return normalize_derived_runtime_state()

    def test_does_not_clear_lease_when_singleton_acquired(self):
        """normalize_derived_runtime_state must not clear NIJA_WRITER_LEASE_ACQUIRED
        when the EntrypointWriterAuthority singleton reports acquired."""
        rt = self._make_runtime()
        self._acquire(rt)

        # Verify preconditions.
        self.assertEqual(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"), "1")

        # Temporarily clear the fencing token so _writer_lineage() returns
        # False — this is the exact scenario from the production failure where
        # a transient env gap triggers the reset path.
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)

        # Bridge the singleton so the patch can see it.
        _ewa = sys.modules.get("bot.entrypoint_writer_authority")
        if _ewa is None:
            import bot.entrypoint_writer_authority as _ewa  # noqa: F811

        _original_singleton = _ewa._SINGLETON
        _ewa._SINGLETON = rt
        original_getter = _ewa.get_entrypoint_writer_authority
        _ewa.get_entrypoint_writer_authority = lambda: rt
        try:
            changes = self._run_normalize()
        finally:
            _ewa._SINGLETON = _original_singleton
            _ewa.get_entrypoint_writer_authority = original_getter

        # The flag must NOT have been cleared.
        self.assertEqual(
            os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"),
            "1",
            "normalize_derived_runtime_state must not clear NIJA_WRITER_LEASE_ACQUIRED "
            f"while the singleton holds the lock. changes={changes}",
        )
        self.assertNotIn(
            "NIJA_WRITER_LEASE_ACQUIRED",
            changes,
            "NIJA_WRITER_LEASE_ACQUIRED must not appear in the changes dict",
        )

    def test_clears_lease_when_singleton_not_acquired(self):
        """normalize_derived_runtime_state may clear the flag when singleton is gone."""
        # No fencing token → lineage fails; no singleton holding the lock.
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"

        # Ensure the module-level singleton is absent or not acquired.
        _ewa = sys.modules.get("bot.entrypoint_writer_authority")
        if _ewa is None:
            import bot.entrypoint_writer_authority as _ewa  # noqa: F811

        _original_singleton = _ewa._SINGLETON
        _ewa._SINGLETON = None
        try:
            changes = self._run_normalize()
        finally:
            _ewa._SINGLETON = _original_singleton

        self.assertEqual(
            os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"),
            "0",
            "When no singleton holds the lock the flag should be cleared",
        )


# ===========================================================================
# Fix 2: authority_heartbeat._check_authority_once defers to singleton
# ===========================================================================

class TestAuthorityHeartbeatSingletonDeference(_Base):

    def _set_healthy_env(self):
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = "abc123"
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "1"

    def test_skips_redis_check_when_singleton_acquired(self):
        """When singleton reports acquired, assert_distributed_writer_authority
        must not be called (no Redis round-trip)."""
        from bot.authority_heartbeat import _check_authority_once

        self._set_healthy_env()

        # Build a minimal mock singleton that reports acquired.
        mock_singleton = MagicMock()
        mock_singleton.acquired = True
        mock_singleton.lost = False

        # Build a fake ewa module.
        fake_ewa = types.ModuleType("bot.entrypoint_writer_authority")
        fake_ewa.get_entrypoint_writer_authority = lambda: mock_singleton

        assert_called = []

        def _assert_dwa():
            assert_called.append(True)

        fake_eac = types.ModuleType("bot.execution_authority_context")
        fake_eac.assert_distributed_writer_authority = _assert_dwa

        with patch.dict(
            sys.modules,
            {
                "bot.entrypoint_writer_authority": fake_ewa,
                "entrypoint_writer_authority": fake_ewa,
                "bot.execution_authority_context": fake_eac,
                "execution_authority_context": fake_eac,
            },
        ):
            # Generation validation also runs; mock it out for isolation.
            with patch(
                "bot.authority_heartbeat._check_authority_once",
                wraps=_check_authority_once,
            ):
                # Mock the generation check to pass so the full function returns ok.
                fake_tracker = types.ModuleType("bot.writer_generation_tracker")
                fake_tracker.validate_generation_for_heartbeat = lambda: (True, "")
                with patch.dict(
                    sys.modules,
                    {
                        "bot.writer_generation_tracker": fake_tracker,
                        "writer_generation_tracker": fake_tracker,
                    },
                ):
                    ok, err = _check_authority_once(timeout_s=5.0)

        self.assertEqual(
            assert_called,
            [],
            "assert_distributed_writer_authority must NOT be called when "
            f"the singleton reports acquired. ok={ok} err={err!r}",
        )
        self.assertTrue(ok, f"Expected ok=True when singleton is healthy, got err={err!r}")

    def test_calls_redis_check_when_singleton_lost(self):
        """When singleton.lost is True the Redis check must run."""
        from bot.authority_heartbeat import _check_authority_once

        self._set_healthy_env()

        mock_singleton = MagicMock()
        mock_singleton.acquired = False
        mock_singleton.lost = True

        fake_ewa = types.ModuleType("bot.entrypoint_writer_authority")
        fake_ewa.get_entrypoint_writer_authority = lambda: mock_singleton

        assert_called = []
        assert_dwa_exc = RuntimeError("lock not owned")

        def _assert_dwa():
            assert_called.append(True)
            raise assert_dwa_exc

        fake_eac = types.ModuleType("bot.execution_authority_context")
        fake_eac.assert_distributed_writer_authority = _assert_dwa

        with patch.dict(
            sys.modules,
            {
                "bot.entrypoint_writer_authority": fake_ewa,
                "entrypoint_writer_authority": fake_ewa,
                "bot.execution_authority_context": fake_eac,
                "execution_authority_context": fake_eac,
            },
        ):
            ok, err = _check_authority_once(timeout_s=5.0)

        # The Redis check must have been called because the singleton is lost.
        self.assertGreater(
            len(assert_called),
            0,
            "assert_distributed_writer_authority must be called when singleton is lost",
        )
        self.assertFalse(ok)

    def test_calls_redis_check_when_no_singleton(self):
        """When no singleton is available the Redis check must run."""
        from bot.authority_heartbeat import _check_authority_once

        self._set_healthy_env()

        fake_ewa = types.ModuleType("bot.entrypoint_writer_authority")
        fake_ewa.get_entrypoint_writer_authority = lambda: None

        assert_called = []

        def _assert_dwa():
            assert_called.append(True)
            raise RuntimeError("no lock")

        fake_eac = types.ModuleType("bot.execution_authority_context")
        fake_eac.assert_distributed_writer_authority = _assert_dwa

        with patch.dict(
            sys.modules,
            {
                "bot.entrypoint_writer_authority": fake_ewa,
                "entrypoint_writer_authority": fake_ewa,
                "bot.execution_authority_context": fake_eac,
                "execution_authority_context": fake_eac,
            },
        ):
            ok, err = _check_authority_once(timeout_s=5.0)

        self.assertGreater(
            len(assert_called),
            0,
            "assert_distributed_writer_authority must be called when no singleton exists",
        )
        self.assertFalse(ok)


# ===========================================================================
# Fix 3/4: writer_generation_scope_repair_patch reads correct Redis key
# ===========================================================================

class TestGenerationScopeRepatchKey(unittest.TestCase):

    def test_patched_get_redis_generation_uses_canonical_key(self):
        """Patched get_redis_generation must read nija:lease:generation."""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "_wgsr_test",
            Path(_REPO_ROOT) / "writer_generation_scope_repair_patch.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        os.environ.pop("NIJA_LEASE_GENERATION_KEY", None)
        os.environ.pop("KRAKEN_PLATFORM_API_KEY", None)
        requested: list[str] = []

        class FakeClient:
            def get(self, key: str):
                requested.append(key)
                return "1234"

        fake_tracker = types.ModuleType("fake_tracker")
        fake_tracker.get_redis_generation = lambda: (0, "")
        fake_tracker._connect_redis = lambda timeout_s=2: (FakeClient(), "")

        assert mod._patch_generation_tracker(fake_tracker)
        gen, err = fake_tracker.get_redis_generation()

        self.assertEqual(err, "")
        self.assertEqual(gen, 1234)
        self.assertEqual(
            requested,
            ["nija:lease:generation"],
            f"Expected ['nija:lease:generation'] but got {requested!r}",
        )

    def test_patched_get_redis_generation_honours_env_override(self):
        """NIJA_LEASE_GENERATION_KEY env override must be used."""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "_wgsr_override_test",
            Path(_REPO_ROOT) / "writer_generation_scope_repair_patch.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        os.environ["NIJA_LEASE_GENERATION_KEY"] = "nija:custom:generation"
        try:
            requested: list[str] = []

            class FakeClient:
                def get(self, key: str):
                    requested.append(key)
                    return "77"

            fake_tracker = types.ModuleType("fake_tracker2")
            fake_tracker.get_redis_generation = lambda: (0, "")
            fake_tracker._connect_redis = lambda timeout_s=2: (FakeClient(), "")

            assert mod._patch_generation_tracker(fake_tracker)
            gen, err = fake_tracker.get_redis_generation()

            self.assertEqual(err, "")
            self.assertEqual(gen, 77)
            self.assertEqual(requested, ["nija:custom:generation"])
        finally:
            os.environ.pop("NIJA_LEASE_GENERATION_KEY", None)


if __name__ == "__main__":
    unittest.main()
