"""Regression tests for capital refresh provenance alias convergence v229."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import bot.runtime_capital_provenance_alias_convergence_v229_patch as v229
import bot.runtime_zero_balance_completeness_v209_patch as v209


@dataclass(frozen=True)
class _Snapshot:
    real_capital: float
    broker_balances: dict[str, float]
    broker_count: int
    expected_brokers: int = 3


def _guard(name: str, *, active: bool, live: dict | None = None, excluded: dict | None = None) -> ModuleType:
    module = ModuleType(name)
    module._REFRESH_CONTEXT = SimpleNamespace(in_refresh=active)

    def current_refresh_fallback_status():
        return {
            "live_brokers": dict(live or {}),
            "excluded_brokers": dict(excluded or {}),
            "brokers": {},
            "used_fallback": False,
            "all_recent": False,
            "source": "live_exchange",
        }

    module.current_refresh_fallback_status = current_refresh_fallback_status
    return module


class CapitalProvenanceAliasV229Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _Snapshot(
            real_capital=345.68,
            broker_balances={"kraken": 250.0, "coinbase": 95.68},
            broker_count=2,
        )

    def test_inactive_first_alias_does_not_hide_active_live_zero(self) -> None:
        inactive = _guard("nija_capital_refresh_stall_guard_v35_prebot", active=False)
        active = _guard(
            "bot.capital_refresh_stall_guard_v35",
            active=True,
            live={"okx": {"value": 0.0}},
        )
        with patch.dict(
            sys.modules,
            {
                "nija_capital_refresh_stall_guard_v35_prebot": inactive,
                "bot.capital_refresh_stall_guard_v35": active,
                "capital_refresh_stall_guard_v35": active,
            },
            clear=False,
        ):
            with patch.object(v209, "_guard_status", v229._merged_active_guard_status):
                augmented, additions = v209._augment_snapshot(self.snapshot)

        self.assertEqual(additions, ("okx",))
        self.assertEqual(augmented.broker_count, 3)
        self.assertEqual(augmented.broker_balances["okx"], 0.0)
        self.assertEqual(augmented.real_capital, self.snapshot.real_capital)

    def test_duplicate_alias_object_is_deduplicated(self) -> None:
        active = _guard(
            "bot.capital_refresh_stall_guard_v35",
            active=True,
            live={"okx": {"value": 0.0}},
        )
        with patch.dict(
            sys.modules,
            {
                "nija_capital_refresh_stall_guard_v35_prebot": active,
                "bot.capital_refresh_stall_guard_v35": active,
                "capital_refresh_stall_guard_v35": active,
            },
            clear=False,
        ):
            rows = v229._active_guard_statuses()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "nija_capital_refresh_stall_guard_v35_prebot")

    def test_active_exclusion_wins_over_live_zero(self) -> None:
        live = _guard(
            "bot.capital_refresh_stall_guard_v35",
            active=True,
            live={"okx": {"value": 0.0}},
        )
        excluded = _guard(
            "capital_refresh_stall_guard_v35",
            active=True,
            excluded={"okx": {"reason": "timeout", "cached_valid": False}},
        )
        with patch.dict(
            sys.modules,
            {
                "nija_capital_refresh_stall_guard_v35_prebot": _guard("prebot", active=False),
                "bot.capital_refresh_stall_guard_v35": live,
                "capital_refresh_stall_guard_v35": excluded,
            },
            clear=False,
        ):
            status = v229._merged_active_guard_status()
            with patch.object(v209, "_guard_status", v229._merged_active_guard_status):
                augmented, additions = v209._augment_snapshot(self.snapshot)

        self.assertNotIn("okx", status["live_brokers"])
        self.assertIn("okx", status["excluded_brokers"])
        self.assertIs(augmented, self.snapshot)
        self.assertEqual(additions, ())

    def test_conflicting_active_values_fail_closed(self) -> None:
        zero = _guard(
            "bot.capital_refresh_stall_guard_v35",
            active=True,
            live={"okx": {"value": 0.0}},
        )
        positive = _guard(
            "capital_refresh_stall_guard_v35",
            active=True,
            live={"okx": {"value": 1.25}},
        )
        with patch.dict(
            sys.modules,
            {
                "nija_capital_refresh_stall_guard_v35_prebot": _guard("prebot", active=False),
                "bot.capital_refresh_stall_guard_v35": zero,
                "capital_refresh_stall_guard_v35": positive,
            },
            clear=False,
        ):
            status = v229._merged_active_guard_status()
            with patch.object(v209, "_guard_status", v229._merged_active_guard_status):
                augmented, additions = v209._augment_snapshot(self.snapshot)

        self.assertNotIn("okx", status["live_brokers"])
        self.assertEqual(status["excluded_brokers"]["okx"]["reason"], "active_alias_value_conflict")
        self.assertIs(augmented, self.snapshot)
        self.assertEqual(additions, ())

    def test_all_aliases_inactive_returns_no_provenance(self) -> None:
        inactive = _guard(
            "bot.capital_refresh_stall_guard_v35",
            active=False,
            live={"okx": {"value": 0.0}},
        )
        with patch.dict(
            sys.modules,
            {
                "nija_capital_refresh_stall_guard_v35_prebot": inactive,
                "bot.capital_refresh_stall_guard_v35": inactive,
                "capital_refresh_stall_guard_v35": inactive,
            },
            clear=False,
        ):
            status = v229._merged_active_guard_status()

        self.assertEqual(status, {})

    def test_positive_missing_balance_is_never_synthesized(self) -> None:
        active = _guard(
            "bot.capital_refresh_stall_guard_v35",
            active=True,
            live={"okx": {"value": 1.25}},
        )
        with patch.dict(
            sys.modules,
            {
                "nija_capital_refresh_stall_guard_v35_prebot": _guard("prebot", active=False),
                "bot.capital_refresh_stall_guard_v35": active,
                "capital_refresh_stall_guard_v35": active,
            },
            clear=False,
        ):
            with patch.object(v209, "_guard_status", v229._merged_active_guard_status):
                augmented, additions = v209._augment_snapshot(self.snapshot)

        self.assertIs(augmented, self.snapshot)
        self.assertEqual(additions, ())
        self.assertNotIn("okx", augmented.broker_balances)


if __name__ == "__main__":
    unittest.main()
