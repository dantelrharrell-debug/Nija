from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


position_tracker_module = load_module("position_tracker_under_test", "position_tracker.py")
startup_sync_module = load_module("startup_position_sync_under_test", "startup_position_sync.py")
kraken_patch_module = load_module("kraken_equity_patch_under_test", "kraken_equity_runtime_patch.py")
runtime_sync_module = load_module("position_sync_runtime_patch_under_test", "position_sync_runtime_repair_patch.py")


class PositionSnapshotSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        position_tracker_module.ENTRY_PRICE_STORE_AVAILABLE = False
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.storage = str(Path(self.tempdir.name) / "positions.json")

    def test_exact_snapshot_repairs_duplicate_zero_price_dilution(self) -> None:
        tracker = position_tracker_module.PositionTracker(self.storage)
        quantity = 5.13699973
        entry = 8.20
        cost = quantity * entry

        self.assertTrue(tracker.track_entry("SOL-USD", entry, quantity, cost))
        self.assertTrue(tracker.track_entry("SOL-USD", 0.0, quantity, 0.0))
        self.assertTrue(tracker.track_entry("SOL-USD", 0.0, quantity, 0.0))
        corrupted = tracker.get_position("SOL-USD")
        self.assertAlmostEqual(corrupted["quantity"], quantity * 3, places=8)
        self.assertLess(corrupted["entry_price"], entry)

        self.assertTrue(
            tracker.sync_position_snapshot(
                symbol="SOL-USD",
                quantity=quantity,
                entry_price=0.0,
                current_price=150.0,
                size_usd=quantity * 150.0,
            )
        )
        repaired = tracker.get_position("SOL-USD")
        self.assertAlmostEqual(repaired["quantity"], quantity, places=8)
        self.assertAlmostEqual(repaired["entry_price"], entry, places=8)
        self.assertAlmostEqual(repaired["size_usd"], cost, places=8)
        self.assertAlmostEqual(
            repaired["last_broker_snapshot_value_usd"],
            quantity * 150.0,
            places=8,
        )

    def test_startup_sync_ignores_stale_override_quantity(self) -> None:
        tracker = position_tracker_module.PositionTracker(self.storage)
        quantity = 5.13699973
        entry = 8.20
        cost = quantity * entry
        tracker.track_entry("SOL-USD", entry, quantity, cost)
        tracker.track_entry("SOL-USD", 0.0, quantity, 0.0)
        tracker.track_entry("SOL-USD", 0.0, quantity, 0.0)

        class StaleEPS:
            def get(self, symbol):
                return SimpleNamespace(price=2.22, quantity=quantity * 3, source="override")

        class Broker:
            connected = True
            position_tracker = tracker

            def get_real_entry_price(self, symbol):
                return None

            def get_positions(self):
                return [
                    {
                        "symbol": "SOL-USD",
                        "quantity": quantity,
                        "current_price": 150.0,
                        "size_usd": quantity * 150.0,
                    }
                ]

        reconciled = startup_sync_module._adopt_broker_positions(
            Broker(),
            "platform:kraken",
            StaleEPS(),
        )
        self.assertEqual(reconciled, 1)
        repaired = tracker.get_position("SOL-USD")
        self.assertAlmostEqual(repaired["quantity"], quantity, places=8)
        self.assertAlmostEqual(repaired["entry_price"], entry, places=8)


class KrakenEquityCanonicalizationTests(unittest.TestCase):
    def test_trade_balance_metadata_is_not_classified_as_crypto(self) -> None:
        payload = {
            "result": {
                "eb": "221.6666",
                "tb": "218.1133",
                "m": "0.0000",
                "SOL": "1.0",
                "ZUSD": "116.09",
            }
        }
        assets = kraken_patch_module._extract_raw_balances(payload)
        self.assertEqual(assets, {"SOL": 1.0})

    def test_total_equity_uses_max_not_addition(self) -> None:
        payload = {
            "ZUSD": "116.09",
            "usd_held": 3.55,
            "total_funds": 225.20,
        }
        positions = [{"symbol": "SOL-USD", "size_usd": 105.56}]
        total = kraken_patch_module._payload_total_equity(payload, positions)
        self.assertAlmostEqual(total, 225.20, places=2)

    def test_wrapped_balance_does_not_recurse_or_mutate_tracker(self) -> None:
        class ExplodingTracker:
            def track_entry(self, *args, **kwargs):
                raise AssertionError("balance hydration must not mutate tracker")

        class KrakenBroker:
            def __init__(self):
                self.calls = 0
                self.connected = True
                self.position_tracker = ExplodingTracker()
                self._last_raw_balances = {
                    "result": {"ZUSD": "116.09", "SOL": "1.0"},
                    "total_funds": 225.20,
                }

            def get_account_balance(self):
                self.calls += 1
                return 225.20

            def get_positions(self):
                return []

            def get_current_price(self, symbol):
                return 105.56

        kraken_patch_module._patch_kraken_class(KrakenBroker)
        broker = KrakenBroker()
        self.assertAlmostEqual(broker.get_account_balance(), 225.20, places=2)
        self.assertEqual(broker.calls, 1)
        positions = broker.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "SOL-USD")


class RecurringPositionSyncTests(unittest.TestCase):
    def test_late_user_broker_is_reconciled_after_first_platform_sync(self) -> None:
        calls = []

        def fake_sync(strategy):
            manager = strategy.multi_account_manager
            names = sorted(runtime_sync_module._connected_brokers(manager))
            calls.append(names)
            for broker in runtime_sync_module._connected_brokers(manager).values():
                broker._startup_position_sync_adopted = True
            return len(names)

        fake_startup_module = types.ModuleType("bot.startup_position_sync")
        fake_startup_module.sync_exchange_positions_on_startup = fake_sync

        class Manager:
            def __init__(self):
                self.platform_brokers = {
                    "kraken": SimpleNamespace(connected=True),
                }
                self.user_brokers = {}

            def refresh_capital_authority(self, *args, **kwargs):
                return {"ready": 1.0, "total_capital": 225.20}

        module = types.ModuleType("bot.multi_account_broker_manager")
        module.MultiAccountBrokerManager = Manager
        runtime_sync_module._patch_mabm(module)
        manager = Manager()

        with patch.dict(
            sys.modules,
            {"bot.startup_position_sync": fake_startup_module},
            clear=False,
        ), patch.dict(
            os.environ,
            {"NIJA_POSITION_SYNC_REFRESH_INTERVAL_S": "30"},
            clear=False,
        ):
            manager.refresh_capital_authority(trigger="platform_ready")
            self.assertEqual(calls[-1], ["platform:kraken"])

            manager.user_brokers = {
                "daivon_frazier": {
                    "kraken": SimpleNamespace(connected=True),
                }
            }
            manager._nija_position_sync_last_attempt_at = 0.0
            manager.refresh_capital_authority(trigger="user_connected")

        self.assertEqual(
            calls[-1],
            ["platform:kraken", "user:daivon_frazier:kraken"],
        )
        self.assertTrue(manager._startup_position_sync_done)


if __name__ == "__main__":
    unittest.main()
