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
