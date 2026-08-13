from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from types import SimpleNamespace


class PrecoreAuthorityHeartbeatV63Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.precore_authority_heartbeat_v63_patch")
        self.saved_env = {
            "NIJA_CORE_THREAD_ALIVE": os.environ.get("NIJA_CORE_THREAD_ALIVE"),
        }
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bot.entrypoint_writer_authority",
                "entrypoint_writer_authority",
                "bot.bot_main",
                "bot_main",
            )
        }

    def tearDown(self) -> None:
        os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
        if self.saved_env["NIJA_CORE_THREAD_ALIVE"] is not None:
            os.environ["NIJA_CORE_THREAD_ALIVE"] = self.saved_env["NIJA_CORE_THREAD_ALIVE"]
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def _install_runtime(
        self,
        *,
        core=None,
        registered: bool = False,
        lost: bool = False,
        deadline_exceeded: bool = False,
        terminal_reason: str = "",
        startup_complete: bool = False,
        shutdown: bool = False,
    ):
        runtime = SimpleNamespace(
            lost=lost,
            terminal_startup_failure_reason=terminal_reason,
            _scan_deadline_exceeded=deadline_exceeded,
            _core_thread=core,
            _core_thread_registered=registered,
        )
        writer_module = types.ModuleType("bot.entrypoint_writer_authority")
        writer_module.get_entrypoint_writer_authority = lambda: runtime
        sys.modules["bot.entrypoint_writer_authority"] = writer_module
        sys.modules.pop("entrypoint_writer_authority", None)

        shutdown_event = SimpleNamespace(is_set=lambda: shutdown)
        bot_main = types.ModuleType("bot.bot_main")
        bot_main._startup_complete = startup_complete
        bot_main._shutdown_event = shutdown_event
        sys.modules["bot.bot_main"] = bot_main
        sys.modules.pop("bot_main", None)
        return runtime

    def test_precore_zero_signal_qualifies_for_startup_grace(self) -> None:
        self._install_runtime()
        active, reason = self.mod._precore_grace_active()
        self.assertTrue(active)
        self.assertEqual(reason, "startup_not_registered")

    def test_grace_ends_when_core_handoff_has_started(self) -> None:
        self._install_runtime(core=object())
        active, reason = self.mod._precore_grace_active()
        self.assertFalse(active)
        self.assertEqual(reason, "core_handoff_started")

    def test_grace_ends_when_scan_deadline_expires(self) -> None:
        self._install_runtime(deadline_exceeded=True)
        active, reason = self.mod._precore_grace_active()
        self.assertFalse(active)
        self.assertEqual(reason, "scan_deadline_exceeded")

    def test_grace_ends_when_startup_completed_without_core(self) -> None:
        self._install_runtime(startup_complete=True)
        active, reason = self.mod._precore_grace_active()
        self.assertFalse(active)
        self.assertEqual(reason, "startup_complete_without_core")

    def test_wrapper_hides_only_precore_zero_from_original_check(self) -> None:
        self._install_runtime()
        fake = types.ModuleType("authority_heartbeat_v63_fake")
        seen = []

        def original(timeout_s: float):
            seen.append((timeout_s, os.environ.get("NIJA_CORE_THREAD_ALIVE")))
            return True, ""

        fake._check_authority_once = original
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
        self.assertTrue(self.mod._patch_authority_heartbeat(fake))

        ok, reason = fake._check_authority_once(1.25)
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(seen, [(1.25, None)])
        self.assertEqual(os.environ.get("NIJA_CORE_THREAD_ALIVE"), "0")

    def test_wrapper_keeps_postcore_zero_fail_closed(self) -> None:
        self._install_runtime(core=object(), registered=True)
        fake = types.ModuleType("authority_heartbeat_v63_postcore_fake")
        seen = []

        def original(timeout_s: float):
            seen.append(os.environ.get("NIJA_CORE_THREAD_ALIVE"))
            return False, "core_thread_dead"

        fake._check_authority_once = original
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
        self.assertTrue(self.mod._patch_authority_heartbeat(fake))

        ok, reason = fake._check_authority_once(1.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "core_thread_dead")
        self.assertEqual(seen, ["0"])


if __name__ == "__main__":
    unittest.main()
