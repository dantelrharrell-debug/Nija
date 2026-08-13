from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from types import SimpleNamespace


class _AliveThread:
    def is_alive(self) -> bool:
        return True


class PrecoreAuthorityHeartbeatV63Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.precore_authority_heartbeat_v63_patch")
        self.saved_env = {
            name: os.environ.get(name)
            for name in (
                "NIJA_CORE_THREAD_ALIVE",
                "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP",
                "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP_REASON",
                "NIJA_RUNTIME_TRADING_STATE",
            )
        }
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bot.entrypoint_writer_authority",
                "entrypoint_writer_authority",
                "bot.bot_main",
                "bot_main",
                "bot.kill_switch",
                "kill_switch",
                "bot.single_execution_authority_kernel",
                "single_execution_authority_kernel",
                "bot.trading_state_machine",
                "trading_state_machine",
            )
        }

    def tearDown(self) -> None:
        for name, value in self.saved_env.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def _install_runtime(
        self,
        *,
        acquired: bool = True,
        core=None,
        registered: bool = False,
        lost: bool = False,
        deadline_exceeded: bool = False,
        terminal_reason: str = "",
        startup_complete: bool = False,
        shutdown: bool = False,
    ):
        runtime = SimpleNamespace(
            acquired=acquired,
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

    def test_precore_grace_requires_acquired_writer(self) -> None:
        self._install_runtime(acquired=False)
        active, reason = self.mod._precore_grace_active()
        self.assertFalse(active)
        self.assertEqual(reason, "writer_not_acquired")

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

    def test_wrapper_preserves_concurrent_core_registration_signal(self) -> None:
        self._install_runtime()
        fake = types.ModuleType("authority_heartbeat_v64_concurrent_fake")

        def original(_timeout_s: float):
            # Simulate register_core_thread publishing a newer liveness signal
            # while the v64 heartbeat wrapper has temporarily hidden pre-core 0.
            os.environ["NIJA_CORE_THREAD_ALIVE"] = "1"
            return True, ""

        fake._check_authority_once = original
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
        self.assertTrue(self.mod._patch_authority_heartbeat(fake))

        ok, reason = fake._check_authority_once(1.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(os.environ.get("NIJA_CORE_THREAD_ALIVE"), "1")

    def test_wrapper_keeps_postcore_zero_fail_closed(self) -> None:
        self._install_runtime(core=_AliveThread(), registered=True)
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

    def _install_recovery_dependencies(self, *, seak_reason: str):
        self._install_runtime(core=_AliveThread(), registered=True)

        kill = types.ModuleType("bot.kill_switch")
        kill.get_kill_switch = lambda: SimpleNamespace(is_active=lambda: False)
        sys.modules["bot.kill_switch"] = kill
        sys.modules.pop("kill_switch", None)

        class FakeSeak:
            def __init__(self):
                self.is_halted = True
                self._halt_reason = seak_reason
                self.resumed = False

            def snapshot(self):
                return {"halted": self.is_halted, "halt_reason": self._halt_reason}

            def resume(self, caller: str = "operator"):
                self.is_halted = False
                self._halt_reason = ""
                self.resumed = caller == "authority_heartbeat_recovery_v64"

        seak = FakeSeak()
        seak_mod = types.ModuleType("bot.single_execution_authority_kernel")
        seak_mod.get_seak = lambda: seak
        sys.modules["bot.single_execution_authority_kernel"] = seak_mod
        sys.modules.pop("single_execution_authority_kernel", None)

        class FakeTradingState:
            EMERGENCY_STOP = "EMERGENCY_STOP"
            OFF = "OFF"
            LIVE_PENDING_CONFIRMATION = "LIVE_PENDING_CONFIRMATION"
            LIVE_ACTIVE = "LIVE_ACTIVE"

        class FakeStateMachine:
            def __init__(self):
                self.state = FakeTradingState.EMERGENCY_STOP
                self.transitions = []

            def get_current_state(self):
                return self.state

            def transition_to(self, target, reason: str):
                self.transitions.append((target, reason))
                self.state = target

        sm = FakeStateMachine()
        tsm = types.ModuleType("bot.trading_state_machine")
        tsm.get_state_machine = lambda: sm
        tsm.TradingState = FakeTradingState
        sys.modules["bot.trading_state_machine"] = tsm
        sys.modules.pop("trading_state_machine", None)
        return seak, sm

    def test_recovery_releases_only_heartbeat_owned_emergency_stop(self) -> None:
        seak, sm = self._install_recovery_dependencies(
            seak_reason="AUTHORITY_HEARTBEAT_EXPIRED: transient core startup race"
        )
        fake = types.ModuleType("authority_heartbeat_v64_recovery_fake")
        fake._check_authority_once = lambda _timeout_s: (True, "")

        os.environ["NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP"] = "1"
        os.environ["NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP_REASON"] = "transient core startup race"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "EMERGENCY_STOP"

        recovered, reason = self.mod._recover_heartbeat_owned_stop(fake)
        self.assertTrue(recovered)
        self.assertEqual(reason, "heartbeat_owned_stop_recovered_to_fail_closed_off")
        self.assertEqual(sm.state, "OFF")
        self.assertTrue(seak.resumed)
        self.assertFalse(seak.is_halted)
        self.assertNotIn("NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP", os.environ)
        # Recovery never force-activates trading.
        self.assertNotEqual(os.environ.get("NIJA_RUNTIME_TRADING_STATE"), "LIVE_ACTIVE")

    def test_recovery_does_not_resume_nonheartbeat_seak_halt(self) -> None:
        seak, sm = self._install_recovery_dependencies(seak_reason="operator emergency halt")
        fake = types.ModuleType("authority_heartbeat_v64_nonowned_fake")
        fake._check_authority_once = lambda _timeout_s: (True, "")
        os.environ["NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP"] = "1"

        recovered, reason = self.mod._recover_heartbeat_owned_stop(fake)
        self.assertFalse(recovered)
        self.assertTrue(reason.startswith("seak_halt_not_heartbeat_owned:"))
        self.assertTrue(seak.is_halted)
        self.assertEqual(sm.state, "EMERGENCY_STOP")


if __name__ == "__main__":
    unittest.main()
