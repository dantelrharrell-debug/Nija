import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from bot import capital_refresh_stall_guard_v35 as guard
from bot import current_capital_snapshot_freshness_repair_patch as repair


class CurrentCapitalFreshnessRepairTests(unittest.TestCase):
    def setUp(self):
        self.original_bot = sys.modules.get("bot")
        self.original_cfsm = sys.modules.get("bot.capital_flow_state_machine")
        self.bot = types.ModuleType("bot")
        self.cfsm = types.ModuleType("bot.capital_flow_state_machine")
        self.cfsm.FRESHNESS_TTL_S = 90.0
        self.bot.capital_flow_state_machine = self.cfsm
        sys.modules["bot"] = self.bot
        sys.modules["bot.capital_flow_state_machine"] = self.cfsm

    def tearDown(self):
        if self.original_bot is None:
            sys.modules.pop("bot", None)
        else:
            sys.modules["bot"] = self.original_bot
        if self.original_cfsm is None:
            sys.modules.pop("bot.capital_flow_state_machine", None)
        else:
            sys.modules["bot.capital_flow_state_machine"] = self.original_cfsm
        repair._INSTALLED = False
        repair._ORIGINAL_INIT = None

    def test_cache_fallback_blocks_freshness_repair(self):
        snapshot = types.SimpleNamespace(
            computed_at=datetime.now(timezone.utc),
            confidence=types.SimpleNamespace(band="MEDIUM"),
            real_capital=100.0,
            broker_count=1,
            expected_brokers=1,
            broker_balances={"okx": 100.0},
            is_fresh=False,
            is_stale=True,
        )
        with patch.object(
            repair,
            "_current_refresh_fallback_status",
            return_value={
                "used_fallback": True,
                "all_recent": False,
                "brokers": {"okx": {"age_s": 120.0, "observed": True}},
            },
        ):
            self.assertFalse(repair._should_repair(snapshot))
        with patch.object(
            repair,
            "_current_refresh_fallback_status",
            return_value={
                "used_fallback": True,
                "all_recent": True,
                "brokers": {"okx": {"age_s": 10.0, "observed": True}},
            },
        ):
            self.assertTrue(repair._should_repair(snapshot))

    def test_constructor_forces_cache_backed_snapshot_stale(self):
        class Snapshot:
            def __init__(self):
                self.computed_at = datetime.now(timezone.utc)
                self.confidence = types.SimpleNamespace(band="MEDIUM")
                self.real_capital = 100.0
                self.broker_count = 1
                self.expected_brokers = 1
                self.broker_balances = {"okx": 100.0}
                self.is_fresh = True
                self.is_stale = False

        self.cfsm.CapitalSnapshot = Snapshot
        with patch.object(
            repair,
            "_current_refresh_fallback_status",
            return_value={
                "used_fallback": True,
                "all_recent": False,
                "brokers": {"okx": {"age_s": 120.0, "observed": True}},
            },
        ):
            self.assertTrue(repair.install_import_hook())
            snapshot = Snapshot()
        self.assertFalse(snapshot.is_fresh)
        self.assertTrue(snapshot.is_stale)

    def test_constructor_repairs_recent_cache_backed_snapshot(self):
        class Snapshot:
            def __init__(self):
                self.computed_at = datetime.now(timezone.utc)
                self.confidence = types.SimpleNamespace(band="MEDIUM")
                self.real_capital = 100.0
                self.broker_count = 1
                self.expected_brokers = 1
                self.broker_balances = {"okx": 100.0}
                self.snapshot_age_s = 120.0
                self.is_fresh = False
                self.is_stale = True

        self.cfsm.CapitalSnapshot = Snapshot
        with patch.object(
            repair,
            "_current_refresh_fallback_status",
            return_value={
                "used_fallback": True,
                "all_recent": True,
                "brokers": {"okx": {"age_s": 10.0, "observed": True}},
            },
        ):
            self.assertTrue(repair.install_import_hook())
            snapshot = Snapshot()

        self.assertTrue(snapshot.is_fresh)
        self.assertFalse(snapshot.is_stale)
        self.assertEqual(snapshot.snapshot_age_s, 0.0)


if __name__ == "__main__":
    unittest.main()
