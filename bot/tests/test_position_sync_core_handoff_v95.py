from __future__ import annotations

import os
import sys
import threading
import time
import types
import unittest
from enum import Enum

from bot import position_sync_core_handoff_v95_patch as v95


class _BrokerType(Enum):
    KRAKEN = "kraken"
    COINBASE = "coinbase"


class PositionSyncCoreHandoffV95Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_timeout = os.environ.get("NIJA_POSITION_FETCH_TIMEOUT_S")
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bot.multi_account_broker_manager",
                "multi_account_broker_manager",
            )
        }
        v95._FLIGHTS.clear()

    def tearDown(self) -> None:
        if self.saved_timeout is None:
            os.environ.pop("NIJA_POSITION_FETCH_TIMEOUT_S", None)
        else:
            os.environ["NIJA_POSITION_FETCH_TIMEOUT_S"] = self.saved_timeout
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        v95._FLIGHTS.clear()

    def test_bounded_fetch_reuses_single_flight_and_consumes_completed_result(self) -> None:
        class SlowBroker:
            connected = True

            def __init__(self) -> None:
                self.calls = 0
                self.release = threading.Event()

            def get_positions(self):
                self.calls += 1
                self.release.wait(2.0)
                return [{"symbol": "BTC-USD", "quantity": 1.0}]

        SlowBroker.get_positions = v95._bounded_get_positions(
            SlowBroker.get_positions,
            "slow",
        )
        broker = SlowBroker()
        os.environ["NIJA_POSITION_FETCH_TIMEOUT_S"] = "0.1"

        for _ in range(2):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                broker.get_positions()
            self.assertLess(time.monotonic() - started, 0.5)

        self.assertEqual(broker.calls, 1)
        broker.release.set()
        time.sleep(0.05)
        result = broker.get_positions()
        self.assertEqual(result[0]["symbol"], "BTC-USD")
        self.assertEqual(broker.calls, 1)

    def test_position_sync_status_requires_every_connected_broker(self) -> None:
        class Broker:
            def __init__(self, synced: bool) -> None:
                self.connected = True
                self._startup_position_sync_adopted = synced

        manager = types.SimpleNamespace(
            platform_brokers={
                _BrokerType.KRAKEN: Broker(True),
                _BrokerType.COINBASE: Broker(False),
            },
            user_brokers={},
        )

        ready, pending, status = v95.position_sync_status(manager)
        self.assertFalse(ready)
        self.assertEqual(pending, ["platform:coinbase"])
        self.assertTrue(status["platform:kraken"])
        self.assertFalse(status["platform:coinbase"])

    def test_v61_activation_blocks_until_position_sync_completes(self) -> None:
        class Broker:
            connected = True

            def __init__(self, synced: bool) -> None:
                self._startup_position_sync_adopted = synced

        kraken = Broker(True)
        coinbase = Broker(False)
        manager = types.SimpleNamespace(
            platform_brokers={
                _BrokerType.KRAKEN: kraken,
                _BrokerType.COINBASE: coinbase,
            },
            user_brokers={},
        )
        mabm = types.ModuleType("bot.multi_account_broker_manager")
        mabm.get_broker_manager = lambda: manager
        mabm.multi_account_broker_manager = manager
        sys.modules["bot.multi_account_broker_manager"] = mabm
        sys.modules["multi_account_broker_manager"] = mabm

        v61 = types.ModuleType("bot.final_production_activation_repair_v61_patch")
        v61._activation_prerequisites = lambda: (
            True,
            [],
            {"core_registered": True, "core_alive": True},
        )
        self.assertTrue(v95._patch_v61(v61))

        ready, blockers, details = v61._activation_prerequisites()
        self.assertFalse(ready)
        self.assertEqual(blockers, ["position_sync:platform:coinbase"])
        self.assertFalse(details["position_sync"]["ready"])

        coinbase._startup_position_sync_adopted = True
        ready, blockers, details = v61._activation_prerequisites()
        self.assertTrue(ready)
        self.assertEqual(blockers, [])
        self.assertTrue(details["position_sync"]["ready"])

    def test_mabm_refresh_corrects_false_pre_latch(self) -> None:
        class Broker:
            connected = True
            _startup_position_sync_adopted = False

        class Manager:
            def __init__(self) -> None:
                self.platform_brokers = {_BrokerType.KRAKEN: Broker()}
                self.user_brokers = {}
                self._startup_position_sync_done = True

            def refresh_capital_authority(self, *args, **kwargs):
                return {"ready": 1.0, "total_capital": 100.0}

        module = types.ModuleType("bot.multi_account_broker_manager")
        module.MultiAccountBrokerManager = Manager
        self.assertTrue(v95._patch_mabm(module))

        manager = Manager()
        manager.refresh_capital_authority()
        self.assertFalse(manager._startup_position_sync_done)

        manager.platform_brokers[_BrokerType.KRAKEN]._startup_position_sync_adopted = True
        manager.refresh_capital_authority()
        self.assertTrue(manager._startup_position_sync_done)


if __name__ == "__main__":
    unittest.main()
