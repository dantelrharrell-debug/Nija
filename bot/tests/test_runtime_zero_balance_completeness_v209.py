"""Regression tests for confirmed zero-balance completeness repair v209."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from types import ModuleType
from unittest.mock import patch

from bot.runtime_zero_balance_completeness_v209_patch import _augment_snapshot


@dataclass(frozen=True)
class _Snapshot:
    real_capital: float
    broker_balances: dict[str, float]
    broker_count: int


def _guard_module(*, live: dict, excluded: dict) -> ModuleType:
    module = ModuleType("bot.capital_refresh_stall_guard_v35")

    def current_refresh_fallback_status():
        return {
            "live_brokers": live,
            "excluded_brokers": excluded,
            "brokers": {},
            "used_fallback": False,
            "all_recent": False,
            "source": "live_exchange",
        }

    module.current_refresh_fallback_status = current_refresh_fallback_status
    return module


class ZeroBalanceCompletenessV209Tests(unittest.TestCase):
    def test_live_zero_balance_broker_is_restored_without_changing_capital(self) -> None:
        snapshot = _Snapshot(
            real_capital=343.03,
            broker_balances={"kraken": 247.91, "coinbase": 95.12},
            broker_count=2,
        )
        guard = _guard_module(
            live={
                "kraken": {"value": 247.91},
                "coinbase": {"value": 95.12},
                "okx": {"value": 0.0},
            },
            excluded={},
        )
        with patch.dict(
            sys.modules,
            {
                "bot.capital_refresh_stall_guard_v35": guard,
                "capital_refresh_stall_guard_v35": guard,
            },
            clear=False,
        ):
            augmented, additions = _augment_snapshot(snapshot)

        self.assertEqual(additions, ("okx",))
        self.assertEqual(augmented.broker_count, 3)
        self.assertEqual(augmented.broker_balances["okx"], 0.0)
        self.assertEqual(augmented.real_capital, snapshot.real_capital)

    def test_excluded_timeout_broker_is_not_restored(self) -> None:
        snapshot = _Snapshot(
            real_capital=343.03,
            broker_balances={"kraken": 247.91, "coinbase": 95.12},
            broker_count=2,
        )
        guard = _guard_module(
            live={"okx": {"value": 0.0}},
            excluded={"okx": {"reason": "timeout", "cached_valid": False}},
        )
        with patch.dict(
            sys.modules,
            {
                "bot.capital_refresh_stall_guard_v35": guard,
                "capital_refresh_stall_guard_v35": guard,
            },
            clear=False,
        ):
            augmented, additions = _augment_snapshot(snapshot)

        self.assertIs(augmented, snapshot)
        self.assertEqual(additions, ())
        self.assertEqual(augmented.broker_count, 2)

    def test_missing_positive_balance_is_never_fabricated(self) -> None:
        snapshot = _Snapshot(
            real_capital=95.12,
            broker_balances={"coinbase": 95.12},
            broker_count=1,
        )
        guard = _guard_module(
            live={"kraken": {"value": 247.91}},
            excluded={},
        )
        with patch.dict(
            sys.modules,
            {
                "bot.capital_refresh_stall_guard_v35": guard,
                "capital_refresh_stall_guard_v35": guard,
            },
            clear=False,
        ):
            augmented, additions = _augment_snapshot(snapshot)

        self.assertIs(augmented, snapshot)
        self.assertEqual(additions, ())


if __name__ == "__main__":
    unittest.main()
