from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from bot import trading_state_machine as module
from bot.execution_router import ExecutionRouter


class _Broker:
    def __init__(self, connected: bool) -> None:
        self.connected = connected


class ExecutionReadinessRegistryFallbackTests(unittest.TestCase):
    def _install_modules(self, *, router_status: dict, platform_brokers: dict[str, _Broker]):
        router = types.SimpleNamespace(
            _venues={},
            get_report=lambda: router_status,
        )
        router_module = types.ModuleType("bot.execution_router")
        router_module.get_execution_router = lambda: router

        manager = types.SimpleNamespace(platform_brokers=platform_brokers)
        manager_module = types.ModuleType("bot.multi_account_broker_manager")
        manager_module.get_broker_manager = lambda: manager
        return router_module, manager_module

    def test_uses_canonical_broker_registry_when_router_registry_is_empty(self):
        router_module, manager_module = self._install_modules(
            router_status={"registered_venues": 0, "session_failed_venues": []},
            platform_brokers={
                "kraken": _Broker(True),
                "coinbase": _Broker(True),
                "okx": _Broker(True),
            },
        )

        with (
            patch.dict(
                sys.modules,
                {
                    "bot.execution_router": router_module,
                    "bot.multi_account_broker_manager": manager_module,
                },
            ),
            patch.object(module, "_strategy_readiness_gate", return_value=(True, "ok")),
        ):
            ok, reason = module._execution_readiness_gate()

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_blocks_when_canonical_broker_registry_has_no_healthy_brokers(self):
        router_module, manager_module = self._install_modules(
            router_status={"registered_venues": 0, "session_failed_venues": []},
            platform_brokers={
                "kraken": _Broker(False),
                "coinbase": _Broker(False),
            },
        )

        with (
            patch.dict(
                sys.modules,
                {
                    "bot.execution_router": router_module,
                    "bot.multi_account_broker_manager": manager_module,
                },
            ),
            patch.object(module, "_strategy_readiness_gate", return_value=(True, "ok")),
        ):
            ok, reason = module._execution_readiness_gate()

        self.assertFalse(ok)
        self.assertIn("registered=2", reason)
        self.assertIn("healthy=0", reason)


if __name__ == "__main__":
    unittest.main()


class ExecutionRouterCanonicalRegistryTests(unittest.TestCase):
    def test_report_uses_canonical_broker_registry_when_router_registry_is_empty(self):
        manager = types.SimpleNamespace(
            get_all_brokers=lambda: {
                "coinbase": types.SimpleNamespace(
                    broker_type=types.SimpleNamespace(value="coinbase"),
                    connected=True,
                ),
                "kraken": types.SimpleNamespace(
                    broker_type=types.SimpleNamespace(value="kraken"),
                    connected=True,
                ),
                "okx": types.SimpleNamespace(
                    broker_type=types.SimpleNamespace(value="okx"),
                    connected=False,
                ),
            }
        )
        manager_module = types.ModuleType("bot.multi_account_broker_manager")
        manager_module.get_broker_manager = lambda: manager

        router = ExecutionRouter()
        with patch.dict(sys.modules, {"bot.multi_account_broker_manager": manager_module}):
            report = router.get_report()

        self.assertEqual(report["registered_venues"], 3)
        self.assertEqual(
            sorted(venue["name"] for venue in report["venues"]),
            ["coinbase", "kraken", "okx"],
        )
        self.assertEqual(
            {venue["name"]: venue["available"] for venue in report["venues"]},
            {"coinbase": True, "kraken": True, "okx": False},
        )
