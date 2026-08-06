import sys
import types
import unittest
import os
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

    def test_fallback_status_uses_canonical_capital_ttl(self):
        expected = {
            "used_fallback": True,
            "all_recent": True,
            "brokers": {"okx": {"age_s": 10.0, "observed": True}},
        }
        with patch.object(
            guard,
            "current_refresh_fallback_status",
            return_value=expected,
        ) as status_getter:
            status = repair._current_refresh_fallback_status()

        self.assertEqual(status, expected)
        status_getter.assert_called_once_with(90.0)

    def test_fallback_status_filters_to_eligible_brokers(self):
        expected = {
            "used_fallback": True,
            "all_recent": False,
            "brokers": {
                "coinbase": {"age_s": 10.0, "observed": True},
                "okx": {"age_s": 15.0, "observed": True},
                "kraken": {"age_s": 120.0, "observed": True},
            },
        }
        with patch.object(
            guard,
            "current_refresh_fallback_status",
            return_value=expected,
        ):
            status = repair._current_refresh_fallback_status(
                eligible_brokers={"coinbase", "okx"},
            )

        self.assertTrue(status["used_fallback"])
        self.assertTrue(status["all_recent"])
        self.assertEqual(set(status["brokers"].keys()), {"coinbase", "okx"})

    def test_fallback_status_ignores_excluded_stale_broker(self):
        expected = {
            "used_fallback": True,
            "all_recent": False,
            "brokers": {
                "kraken": {"age_s": 120.0, "observed": True},
            },
        }
        with patch.object(
            guard,
            "current_refresh_fallback_status",
            return_value=expected,
        ):
            status = repair._current_refresh_fallback_status(
                active_brokers={"coinbase", "okx"},
            )

        self.assertFalse(status["used_fallback"])
        self.assertTrue(status["all_recent"])
        self.assertEqual(status["brokers"], {})

    def test_should_repair_uses_eligible_broker_count_instead_of_configured(self):
        snapshot = types.SimpleNamespace(
            computed_at=datetime.now(timezone.utc),
            confidence=types.SimpleNamespace(band="MEDIUM"),
            real_capital=100.0,
            broker_count=2,
            expected_brokers=3,
            eligible_brokers={"coinbase", "okx"},
            broker_balances={"coinbase": 40.0, "okx": 60.0},
            is_fresh=False,
            is_stale=True,
        )
        with patch.object(
            repair,
            "_current_refresh_fallback_status",
            return_value={
                "used_fallback": False,
                "all_recent": True,
                "brokers": {},
            },
        ):
            self.assertTrue(repair._should_repair(snapshot))

    def test_install_is_diagnostic_only(self):
        self.assertTrue(repair.install_import_hook())
        self.assertEqual(
            "diagnostic_only",
            os.environ.get("NIJA_CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR"),
        )
        self.assertEqual(
            "1",
            os.environ.get("NIJA_CURRENT_CAPITAL_SNAPSHOT_FRESHNESS_REPAIR_DIAGNOSTIC"),
        )


if __name__ == "__main__":
    unittest.main()
