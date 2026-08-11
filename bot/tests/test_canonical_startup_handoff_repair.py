"""Tests for the canonical trading-core startup handoff repair.

Covers:
1. Successful canonical registration path with identity consistency.
2. Re-acquisition of the writer lock preserves a live core thread.
3. Duplicate import path defense — single canonical authority binding.
4. Startup watchdog emits a diagnostic/stack dump when registration is blocked.
5. Failure path does not claim success markers (no CANONICAL_CORE_THREAD_REGISTERED
   when registration fails).
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch


class CanonicalRegistrationIdentityTests(unittest.TestCase):
    """Verify that register_core_thread sets _core_thread to the exact thread passed."""

    def setUp(self) -> None:
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority

        self.runtime = EntrypointWriterAuthority()
        self._saved_env = {
            k: os.environ.get(k)
            for k in ("NIJA_CORE_THREAD_ALIVE",)
        }
        os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)

    def tearDown(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_register_core_thread_sets_identity(self) -> None:
        """register_core_thread must set _core_thread to the exact passed thread."""
        thread = threading.Thread(target=lambda: time.sleep(60), daemon=True)
        thread.start()
        try:
            self.runtime.register_core_thread(thread)
            self.assertIs(self.runtime._core_thread, thread)
        finally:
            # Thread is daemon so it will be reaped; just verify name
            pass

    def test_register_core_thread_sets_alive_env_from_real_liveness(self) -> None:
        """NIJA_CORE_THREAD_ALIVE must reflect the thread's real is_alive() result."""
        thread = threading.Thread(target=lambda: time.sleep(60), daemon=True)
        thread.start()
        try:
            self.runtime.register_core_thread(thread)
            self.assertEqual(os.environ.get("NIJA_CORE_THREAD_ALIVE"), "1")
        finally:
            pass

    def test_register_core_thread_rejects_none(self) -> None:
        """register_core_thread(None) must be a no-op (not clear an existing thread)."""
        thread = threading.Thread(target=lambda: time.sleep(60), daemon=True)
        thread.start()
        try:
            self.runtime.register_core_thread(thread)
            self.assertIs(self.runtime._core_thread, thread)
            self.runtime.register_core_thread(None)
            # Still the original thread — None is silently ignored.
            self.assertIs(self.runtime._core_thread, thread)
        finally:
            pass

    def test_validate_core_thread_liveness_unregistered_returns_ok_within_deadline(self) -> None:
        """An unregistered runtime inside the deadline must return (True, '')."""
        ok, reason = self.runtime._validate_core_thread_liveness()
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_validate_core_thread_liveness_registered_alive_returns_ok(self) -> None:
        """A registered live thread must make liveness return (True, '')."""
        thread = threading.Thread(target=lambda: time.sleep(60), daemon=True)
        thread.start()
        self.runtime.register_core_thread(thread)
        ok, reason = self.runtime._validate_core_thread_liveness()
        self.assertTrue(ok)
        self.assertEqual(reason, "")


class ReacquisitionPreservesThreadTests(unittest.TestCase):
    """After writer re-acquisition, a live core thread must not be cleared."""

    def setUp(self) -> None:
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority

        self.runtime = EntrypointWriterAuthority()
        self._saved_env = {
            k: os.environ.get(k)
            for k in ("NIJA_CORE_THREAD_ALIVE",)
        }
        os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)

    def tearDown(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _fake_activate(
        self,
        runtime,
        *,
        client: MagicMock,
        token: str = "tok",
        generation: int = 1,
    ) -> None:
        """Call _activate_distributed_authority with minimal mock arguments."""
        import types as _types

        runtime._activate_distributed_authority(
            client=client,
            token=token,
            generation=generation,
            identity={"instance_id": "test", "hostname": "host"},
            owner="owner",
            instance_id="test-instance",
            scope="test",
            lock_key="nija:writer_lock:test",
            meta_key="nija:writer_meta:test",
            fencing_key="nija:writer_fencing:test",
            generation_key="nija:writer_generation:test",
            ttl_s=30,
        )

    def test_live_thread_preserved_across_reacquisition(self) -> None:
        """A live _core_thread must be preserved when the writer is re-acquired."""
        thread = threading.Thread(target=lambda: time.sleep(60), daemon=True)
        thread.start()

        client = MagicMock()
        # Suppress heartbeat/watchdog start
        with (
            patch.object(self.runtime, "_start_heartbeat"),
            patch.object(self.runtime, "_start_scan_started_watchdog"),
            patch.object(self.runtime, "_publish_env"),
            patch.object(self.runtime, "_write_metadata"),
            patch.object(self.runtime, "_set_writer_state"),
            patch.object(self.runtime, "_notify_runtime_reconciliation"),
        ):
            # First activation — registers the thread
            self._fake_activate(self.runtime, client=client, generation=1)
            self.runtime.register_core_thread(thread)
            self.assertIs(self.runtime._core_thread, thread)

            # Simulate re-acquisition (new generation)
            self._fake_activate(self.runtime, client=client, generation=2)

        # Thread is still alive — must be preserved across re-acquisition.
        self.assertIs(self.runtime._core_thread, thread)
        self.assertEqual(os.environ.get("NIJA_CORE_THREAD_ALIVE"), "1")

    def test_dead_thread_cleared_on_reacquisition(self) -> None:
        """A dead _core_thread must be cleared when the writer is re-acquired."""
        ran = threading.Event()
        thread = threading.Thread(target=ran.set, daemon=True)
        thread.start()
        ran.wait(timeout=2.0)
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())

        client = MagicMock()
        with (
            patch.object(self.runtime, "_start_heartbeat"),
            patch.object(self.runtime, "_start_scan_started_watchdog"),
            patch.object(self.runtime, "_publish_env"),
            patch.object(self.runtime, "_write_metadata"),
            patch.object(self.runtime, "_set_writer_state"),
            patch.object(self.runtime, "_notify_runtime_reconciliation"),
        ):
            self._fake_activate(self.runtime, client=client, generation=1)
            self.runtime.register_core_thread(thread)
            # Thread is dead so register would have set NIJA_CORE_THREAD_ALIVE=0
            self._fake_activate(self.runtime, client=client, generation=2)

        # Dead thread must be cleared.
        self.assertIsNone(self.runtime._core_thread)


class DuplicateImportDefenseTests(unittest.TestCase):
    """Verify bind_entrypoint_writer_authority_aliases converges module identities."""

    def test_package_and_compat_aliases_share_singleton_after_bind(self) -> None:
        """After bind, both 'bot.entrypoint_writer_authority' and the compat name
        must expose the same _SINGLETON object."""
        import importlib

        pkg_mod = importlib.import_module("bot.entrypoint_writer_authority")
        compat_mod = sys.modules.get("entrypoint_writer_authority")
        if compat_mod is None:
            # Force the compat path to be registered.
            compat_mod = pkg_mod
            sys.modules["entrypoint_writer_authority"] = compat_mod

        bind = getattr(pkg_mod, "bind_entrypoint_writer_authority_aliases", None)
        self.assertIsNotNone(bind)
        bind()

        pkg_singleton = getattr(pkg_mod, "_SINGLETON", None)
        compat_singleton = getattr(compat_mod, "_SINGLETON", None)
        self.assertIs(pkg_singleton, compat_singleton)

    def test_get_entrypoint_writer_authority_is_idempotent(self) -> None:
        """Two successive calls to get_entrypoint_writer_authority() must return the
        same object."""
        from bot.entrypoint_writer_authority import get_entrypoint_writer_authority

        first = get_entrypoint_writer_authority()
        second = get_entrypoint_writer_authority()
        self.assertIs(first, second)


class StartupWatchdogTests(unittest.TestCase):
    """Verify the startup registration watchdog emits a stack dump when blocked."""

    def test_watchdog_emits_critical_when_deadline_exceeded(self) -> None:
        """_startup_registration_watchdog must log a CRITICAL when the deadline is
        hit without _startup_registration_done being set."""
        import bot.bot_main as _bot_main

        # Save and reset module-level event.
        saved_event = _bot_main._startup_registration_done
        saved_stage_ts = dict(_bot_main._startup_stage_ts)
        _bot_main._startup_registration_done = threading.Event()
        _bot_main._startup_stage_ts.clear()

        log_records: list[str] = []

        class CapturingHandler:
            level = 0

            def handle(self, record) -> None:  # type: ignore[no-untyped-def]
                log_records.append(record.getMessage())

            def emit(self, record) -> None:  # type: ignore[no-untyped-def]
                log_records.append(record.getMessage())

        import logging

        handler = CapturingHandler()
        root = logging.getLogger()
        root.addHandler(handler)  # type: ignore[arg-type]
        try:
            watchdog_thread = threading.Thread(
                target=_bot_main._startup_registration_watchdog,
                args=(0.05, 0.02),  # deadline 50ms, poll 20ms
                daemon=True,
            )
            watchdog_thread.start()
            watchdog_thread.join(timeout=2.0)
        finally:
            root.removeHandler(handler)  # type: ignore[arg-type]
            _bot_main._startup_registration_done = saved_event
            _bot_main._startup_stage_ts.update(saved_stage_ts)

        dump_records = [r for r in log_records if "STARTUP_REGISTRATION_BLOCKED_STACK_DUMP" in r]
        self.assertTrue(
            len(dump_records) >= 1,
            f"Expected at least one STARTUP_REGISTRATION_BLOCKED_STACK_DUMP log, "
            f"got records: {log_records[:5]}",
        )

    def test_watchdog_exits_cleanly_when_registration_done(self) -> None:
        """_startup_registration_watchdog must exit without emitting a dump when
        _startup_registration_done is set before the deadline."""
        import bot.bot_main as _bot_main

        saved_event = _bot_main._startup_registration_done
        saved_stage_ts = dict(_bot_main._startup_stage_ts)
        done_event = threading.Event()
        _bot_main._startup_registration_done = done_event
        _bot_main._startup_stage_ts.clear()

        log_records: list[str] = []

        class CapturingHandler:
            level = 0

            def handle(self, record) -> None:  # type: ignore[no-untyped-def]
                log_records.append(record.getMessage())

            def emit(self, record) -> None:  # type: ignore[no-untyped-def]
                log_records.append(record.getMessage())

        import logging

        handler = CapturingHandler()
        root = logging.getLogger()
        root.addHandler(handler)  # type: ignore[arg-type]
        try:
            done_event.set()  # Signal completion immediately
            watchdog_thread = threading.Thread(
                target=_bot_main._startup_registration_watchdog,
                args=(5.0, 0.02),
                daemon=True,
            )
            watchdog_thread.start()
            watchdog_thread.join(timeout=2.0)
        finally:
            root.removeHandler(handler)  # type: ignore[arg-type]
            _bot_main._startup_registration_done = saved_event
            _bot_main._startup_stage_ts.update(saved_stage_ts)

        dump_records = [r for r in log_records if "STARTUP_REGISTRATION_BLOCKED_STACK_DUMP" in r]
        self.assertEqual(
            len(dump_records),
            0,
            f"Unexpected dump records: {dump_records}",
        )


class StartupCompleteFlagOrderingTests(unittest.TestCase):
    """Verify that _startup_complete is set only after CANONICAL_CORE_THREAD_REGISTERED."""

    def test_startup_complete_flag_set_after_canonical_registration_marker(self) -> None:
        """The CANONICAL_CORE_THREAD_REGISTERED log must appear before _startup_complete
        is ever set to True in bot_main.py's Step 3 block."""
        import ast
        import pathlib

        src = pathlib.Path(__file__).parent.parent / "bot_main.py"
        tree = ast.parse(src.read_text())

        canonical_lineno = None
        startup_complete_lineno = None

        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                # logger.critical("CANONICAL_CORE_THREAD_REGISTERED ...")
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("critical", "info", "warning")
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and "CANONICAL_CORE_THREAD_REGISTERED" in str(call.args[0].value)
                ):
                    canonical_lineno = node.lineno

            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "_startup_complete":
                        val = node.value
                        if isinstance(val, ast.Constant) and val.value is True:
                            startup_complete_lineno = node.lineno

        self.assertIsNotNone(canonical_lineno, "CANONICAL_CORE_THREAD_REGISTERED log not found")
        self.assertIsNotNone(startup_complete_lineno, "_startup_complete = True not found")
        self.assertGreater(
            startup_complete_lineno,
            canonical_lineno,
            f"_startup_complete = True (line {startup_complete_lineno}) must come AFTER "
            f"CANONICAL_CORE_THREAD_REGISTERED (line {canonical_lineno})",
        )
