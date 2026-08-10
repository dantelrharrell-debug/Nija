from __future__ import annotations

import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from bot import downstream_risk_governor_equity_repair_patch as downstream
from bot import kraken_all_account_supervision_v86 as kraken_supervision
from bot import live_broker_profit_exit_convergence_v25 as connectivity
from bot import startup_runtime_safety
from bot.entrypoint_writer_authority import EntrypointWriterAuthority
from bot.multi_account_broker_manager import BrokerType, MultiAccountBrokerManager


class _BrokerType:
    def __init__(self, value: str) -> None:
        self.value = value


class RuntimeStartupHandoffV87Tests(unittest.TestCase):
    def test_downstream_installer_never_imports_unloaded_runtime_graph(self) -> None:
        names = (
            "bot.downstream_blocker_guard",
            "downstream_blocker_guard",
            "bot.execution_pipeline",
            "execution_pipeline",
            "bot.pre_trade_risk_engine",
            "pre_trade_risk_engine",
            "bot.execution_engine",
            "execution_engine",
        )
        previous = {name: sys.modules.pop(name, None) for name in names}
        try:
            self.assertFalse(downstream._try_patch_loaded())
        finally:
            for name, module in previous.items():
                if module is not None:
                    sys.modules[name] = module

    def test_startup_autowire_only_observes_loaded_modules(self) -> None:
        target = "bot.test_v87_runtime_target"
        previous = sys.modules.pop(target, None)
        try:
            self.assertIsNone(
                startup_runtime_safety._resolve_class((target,), "Target")
            )
            module = ModuleType(target)
            module.Target = type("Target", (), {})
            sys.modules[target] = module
            self.assertIs(
                startup_runtime_safety._resolve_class((target,), "Target"),
                module.Target,
            )
        finally:
            sys.modules.pop(target, None)
            if previous is not None:
                sys.modules[target] = previous

    def test_unregistered_core_is_reported_inactive_without_failing_writer(self) -> None:
        runtime = EntrypointWriterAuthority()

        ok, reason = runtime._validate_core_thread_liveness()

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(runtime._scan_deadline_armed_at, 0.0)

    def test_scan_deadline_is_armed_from_engine_handoff_once(self) -> None:
        runtime = EntrypointWriterAuthority()
        runtime._instance_id = "instance"
        runtime._generation = 7
        runtime._start_scan_started_watchdog = MagicMock()
        self.addCleanup(os.environ.pop, "NIJA_SCAN_START_DEADLINE_ARMED_AT", None)
        self.addCleanup(os.environ.pop, "NIJA_SCAN_START_DEADLINE_SOURCE", None)

        with patch("bot.entrypoint_writer_authority.time.time", return_value=1234.5):
            runtime.arm_scan_start_deadline("bot_main_step3")
            runtime.arm_scan_start_deadline("duplicate")

        self.assertEqual(runtime._scan_deadline_armed_at, 1234.5)
        self.assertEqual(runtime._scan_deadline_arm_source, "bot_main_step3")
        self.assertEqual(
            os.environ["NIJA_SCAN_START_DEADLINE_SOURCE"], "bot_main_step3"
        )
        runtime._start_scan_started_watchdog.assert_called_once_with()

    def test_writer_releases_after_bounded_core_registration_window(self) -> None:
        runtime = EntrypointWriterAuthority()
        runtime._acquired_at = 100.0
        runtime._instance_id = "instance"
        runtime._generation = 9

        with (
            patch.dict(
                os.environ,
                {"NIJA_CORE_REGISTRATION_DEADLINE_S": "60"},
                clear=False,
            ),
            patch("bot.entrypoint_writer_authority.time.time", return_value=161.0),
        ):
            ok, reason = runtime._validate_core_thread_liveness()

        self.assertFalse(ok)
        self.assertIn("core_thread_registration_deadline_exceeded", reason)

    def test_heartbeat_stops_before_redis_renewal_on_core_deadline(self) -> None:
        runtime = EntrypointWriterAuthority()
        runtime._client = MagicMock()
        runtime._release_owned_lock_for_reelection = MagicMock()

        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(runtime, "_check_authority_invariant", return_value=(True, "")),
            patch.object(
                runtime,
                "_validate_core_thread_liveness",
                return_value=(False, "core_thread_registration_deadline_exceeded"),
            ),
        ):
            ok, reason = runtime._heartbeat_tick()

        self.assertFalse(ok)
        self.assertEqual(reason, "core_thread_registration_deadline_exceeded")
        runtime._release_owned_lock_for_reelection.assert_called_once_with(reason)
        runtime._client.eval.assert_not_called()

    def test_core_registration_restart_is_bounded_and_nonzero(self) -> None:
        from bot import bot_main

        timer = MagicMock()
        bot_main._core_registration_restart_timer = None
        self.addCleanup(
            setattr,
            bot_main,
            "_core_registration_restart_timer",
            None,
        )
        with (
            patch.dict(
                os.environ,
                {"NIJA_CORE_REGISTRATION_RESTART_GRACE_S": "3"},
                clear=False,
            ),
            patch.object(bot_main.threading, "Timer", return_value=timer) as factory,
            patch.object(bot_main.os, "_exit") as force_exit,
        ):
            bot_main._schedule_core_registration_restart("deadline")
            callback = factory.call_args.args[1]
            callback()

        factory.assert_called_once()
        self.assertEqual(factory.call_args.args[0], 3.0)
        self.assertTrue(timer.daemon)
        timer.start.assert_called_once_with()
        force_exit.assert_called_once_with(75)

    def test_account_status_uses_actual_platform_and_user_registries(self) -> None:
        manager = object.__new__(MultiAccountBrokerManager)
        manager._platform_brokers = {
            BrokerType.COINBASE: SimpleNamespace(connected=True),
            BrokerType.OKX: SimpleNamespace(connected=True),
        }
        manager._platform_failed_types = {BrokerType.KRAKEN}
        manager._all_user_brokers = {
            ("tania_gilbert", BrokerType.KRAKEN): SimpleNamespace(
                connected=False,
                credentials_configured=True,
            ),
            ("daivon_frazier", BrokerType.KRAKEN): SimpleNamespace(
                connected=False,
                credentials_configured=True,
            ),
        }
        manager.user_brokers = {}
        manager._failed_user_connections = {
            ("tania_gilbert", BrokerType.KRAKEN): "platform_not_ready"
        }
        manager._users_without_credentials = {}

        status = manager._account_registry_status({})

        self.assertEqual(status["platform_registered"], 3)
        self.assertEqual(status["platform_connected"], 2)
        self.assertEqual(status["platform_disconnected"], 1)
        self.assertEqual(status["user_registered"], 2)
        self.assertEqual(status["user_connected"], 0)
        self.assertEqual(status["user_disconnected"], 2)
        self.assertFalse(status["all_registered_trading"])

    def test_account_status_counts_registration_without_broker_object(self) -> None:
        manager = object.__new__(MultiAccountBrokerManager)
        manager._platform_brokers = {
            BrokerType.KRAKEN: SimpleNamespace(connected=True)
        }
        manager._platform_failed_types = set()
        manager._all_user_brokers = {}
        manager.user_brokers = {}
        manager._user_metadata = {
            "alice": {
                "enabled": True,
                "brokers": {BrokerType.KRAKEN: False},
            }
        }
        manager._failed_user_connections = {
            ("alice", BrokerType.KRAKEN): "broker_creation_failed"
        }
        manager._users_without_credentials = {}

        status = manager._account_registry_status({})

        self.assertEqual(status["user_registered"], 1)
        self.assertEqual(status["user_connected"], 0)
        self.assertEqual(status["user_failures"], 1)
        self.assertFalse(status["all_registered_trading"])

    def test_platform_gated_kraken_user_keeps_credential_presence(self) -> None:
        from bot.broker_manager import _kraken_user_credentials_configured

        with patch.dict(
            os.environ,
            {
                "KRAKEN_USER_TANIA_GILBERT_API_KEY": "configured-key",
                "KRAKEN_USER_TANIA_GILBERT_API_SECRET": "configured-secret",
            },
            clear=True,
        ):
            self.assertTrue(
                _kraken_user_credentials_configured("tania_gilbert")
            )

    def test_ntp_offset_uses_documented_local_minus_reference_sign(self) -> None:
        from bot import global_kraken_nonce as nonce

        ntp_module = SimpleNamespace(
            NTPClient=lambda: SimpleNamespace(
                request=lambda *args, **kwargs: SimpleNamespace(offset=0.25)
            )
        )
        with patch.dict(sys.modules, {"ntplib": ntp_module}):
            result = nonce.check_ntp_sync()

        self.assertEqual(result["offset_s"], -0.25)
        self.assertTrue(result["ok"])

    def test_clock_probe_falls_back_to_kraken_https_time(self) -> None:
        from bot import global_kraken_nonce as nonce

        ntp_module = SimpleNamespace(
            NTPClient=lambda: SimpleNamespace(
                request=lambda *args, **kwargs: (_ for _ in ()).throw(
                    TimeoutError("udp blocked")
                )
            )
        )
        with (
            patch.dict(sys.modules, {"ntplib": ntp_module}),
            patch.object(nonce, "_fetch_kraken_server_time_ms", return_value=1_000_000),
            patch.object(nonce.time, "time", side_effect=[1000.1, 1000.3]),
        ):
            result = nonce.check_ntp_sync()

        self.assertAlmostEqual(result["offset_s"], -0.3)
        self.assertEqual(result["server"], "api.kraken.com/0/public/Time")
        self.assertTrue(result["ok"])

    def test_kraken_clock_readiness_fails_closed_on_drift(self) -> None:
        from bot import broker_manager

        with patch.object(
            broker_manager,
            "check_ntp_sync",
            return_value={
                "ok": False,
                "offset_s": 2.25,
                "server": "api.kraken.com/0/public/Time",
                "error": "",
            },
        ):
            ready, reason, status = broker_manager._kraken_clock_readiness()

        self.assertFalse(ready)
        self.assertIn("clock_drift_out_of_tolerance", reason)
        self.assertEqual(status["offset_s"], 2.25)

    def test_platform_connectivity_cannot_be_satisfied_by_kraken_user(self) -> None:
        platform_kraken = SimpleNamespace(connected=False)
        user_kraken = SimpleNamespace(connected=True)
        kraken = _BrokerType("kraken")
        manager = SimpleNamespace(
            _platform_brokers={kraken: platform_kraken},
            _all_user_brokers={("customer", kraken): user_kraken},
            user_brokers={"customer": {kraken: user_kraken}},
        )

        platform = connectivity._platform_connectivity(manager)
        users = connectivity._kraken_user_connectivity(manager)

        self.assertFalse(platform["kraken"])
        self.assertEqual(
            users,
            {
                "registered": 1,
                "connected": 1,
                "disconnected": 0,
                "all_connected": True,
            },
        )

    def test_kraken_supervision_uses_canonical_manager_singleton(self) -> None:
        target = "bot.multi_account_broker_manager"
        previous = sys.modules.get(target)
        get_broker_manager = MagicMock(
            return_value=SimpleNamespace(_all_user_brokers={}, user_brokers={})
        )
        module = ModuleType(target)
        module.get_broker_manager = get_broker_manager
        sys.modules[target] = module
        try:
            state = kraken_supervision.reconcile_once()
        finally:
            if previous is None:
                sys.modules.pop(target, None)
            else:
                sys.modules[target] = previous

        get_broker_manager.assert_called_once_with()
        self.assertEqual(state["reason"], "all_registered_kraken_users_connected")

    def test_platform_kraken_recovery_uses_canonical_manager_singleton(self) -> None:
        target = "bot.multi_account_broker_manager"
        previous = sys.modules.get(target)
        manager = SimpleNamespace(_platform_brokers={})
        get_broker_manager = MagicMock(return_value=manager)
        module = ModuleType(target)
        module.get_broker_manager = get_broker_manager
        sys.modules[target] = module
        try:
            resolved = kraken_supervision.v44._manager()
        finally:
            if previous is None:
                sys.modules.pop(target, None)
            else:
                sys.modules[target] = previous

        self.assertIs(resolved, manager)
        get_broker_manager.assert_called_once_with()

    def test_kraken_watchdogs_never_import_unloaded_manager_graph(self) -> None:
        names = ("bot.multi_account_broker_manager", "multi_account_broker_manager")
        previous = {name: sys.modules.pop(name, None) for name in names}
        try:
            with patch.object(
                kraken_supervision.v44.importlib, "import_module"
            ) as import_module:
                self.assertIsNone(kraken_supervision.v44._manager())
            state = kraken_supervision.reconcile_once()
        finally:
            for name, module in previous.items():
                if module is not None:
                    sys.modules[name] = module

        import_module.assert_not_called()
        self.assertFalse(state["ok"])
        self.assertIn("canonical_manager_not_loaded", state["reason"])

    def test_bot_main_installs_all_account_supervision_after_prebootstrap(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "bot_main.py").read_text(
            encoding="utf-8"
        )

        prebootstrap = source.index("manager = prepare_canonical_broker_runtime()")
        supervision = source.index("install_kraken_all_account_supervision()")
        engine = source.index('logger.info("\\n[STEP 3] Starting Trading Loop")')
        self.assertLess(prebootstrap, supervision)
        self.assertLess(supervision, engine)


if __name__ == "__main__":
    unittest.main()
