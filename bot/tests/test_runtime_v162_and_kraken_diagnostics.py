from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot import broker_manager
from bot import runtime_capital_late_observation_fence_v162_patch as v162


class _AliveThread:
    def is_alive(self) -> bool:
        return True


class _Observation:
    def __init__(
        self,
        value: float,
        observed_monotonic: float,
        observed_epoch: float,
        sequence: int,
    ) -> None:
        self.value = value
        self.observed_monotonic = observed_monotonic
        self.observed_epoch = observed_epoch
        self.sequence = sequence


class RuntimeCapitalV162Tests(unittest.TestCase):
    def setUp(self) -> None:
        v162._SATURATION_RECOVERY_USED.clear()

    def tearDown(self) -> None:
        v162._SATURATION_RECOVERY_USED.clear()

    @staticmethod
    def _guard(flight: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(
            _IN_FLIGHT={"kraken": flight},
            _IN_FLIGHT_LOCK=threading.RLock(),
            _BROKER_SEQUENCE={"kraken": 4},
            _OBSERVATIONS={
                "kraken": _Observation(
                    value=100.0,
                    observed_monotonic=490.0,
                    observed_epoch=1.0,
                    sequence=4,
                )
            },
            _OBSERVATION_LOCK=threading.RLock(),
            _Observation=_Observation,
            _freshness_ttl_seconds=lambda: 90.0,
        )

    def test_saturation_recovery_requires_fresh_observation_and_is_bounded(self) -> None:
        flight = SimpleNamespace(thread=_AliveThread(), started_monotonic=100.0, sequence=4)
        guard = self._guard(flight)
        existing_orphan = SimpleNamespace(thread=_AliveThread())
        orphaned_flights = {"kraken": [existing_orphan]}
        fake_v161 = SimpleNamespace(
            _prune_orphans=lambda broker_id: orphaned_flights[broker_id],
            _max_orphaned_flights=lambda: 1,
            _stale_flight_after_seconds=lambda broker_id: 30.0,
            _ORPHANED_FLIGHTS=orphaned_flights,
        )

        with patch.object(v162, "_v161", return_value=fake_v161), patch.object(
            v162.time, "monotonic", return_value=500.0
        ):
            v162._supersede_with_observation_fence(guard, {"kraken": object()})

        self.assertNotIn("kraken", guard._IN_FLIGHT)
        self.assertEqual(guard._BROKER_SEQUENCE["kraken"], 5)
        self.assertEqual(guard._OBSERVATIONS["kraken"].sequence, 5)
        self.assertEqual(orphaned_flights["kraken"], [existing_orphan, flight])
        self.assertIn("kraken", v162._SATURATION_RECOVERY_USED)

        replacement = SimpleNamespace(thread=_AliveThread(), started_monotonic=100.0, sequence=6)
        guard._IN_FLIGHT["kraken"] = replacement
        with patch.object(v162, "_v161", return_value=fake_v161), patch.object(
            v162.time, "monotonic", return_value=600.0
        ):
            v162._supersede_with_observation_fence(guard, {"kraken": object()})

        self.assertIs(guard._IN_FLIGHT["kraken"], replacement)
        self.assertEqual(orphaned_flights["kraken"], [existing_orphan, flight])


class KrakenSizingDiagnosticsTests(unittest.TestCase):
    def test_insufficient_funds_is_fail_closed_without_unbound_diagnostic(self) -> None:
        broker = object.__new__(broker_manager.KrakenBroker)
        broker.api = object()
        broker.broker_type = SimpleNamespace(value="kraken")
        broker.account_type = broker_manager.AccountType.PLATFORM
        broker.exit_only_mode = False
        broker.supports_symbol = lambda symbol: True
        broker.get_account_balance_detailed = lambda: {"trading_balance": 35.0}

        with patch.object(
            broker_manager, "_reject_if_unauthorized_order_submit", return_value=None
        ), patch.object(
            broker_manager, "_check_broker_isolation", return_value=None
        ), patch.object(
            broker_manager, "validate_kraken_symbol", None
        ), patch.object(
            broker_manager, "convert_to_kraken", None
        ), patch.object(
            broker_manager, "normalize_symbol_for_broker", return_value="ETH-USD"
        ), patch.object(
            broker_manager, "get_tier_from_balance", None
        ), patch.object(
            broker_manager, "validate_trade_size", None
        ), patch.object(
            broker_manager, "_kraken_quarantine_active", False
        ), patch.object(
            broker_manager, "KRAKEN_MINIMUM_ORDER_USD", 10.0
        ), patch.dict(
            broker_manager.os.environ, {"MAX_TRADE_PERCENT": "0.08"}
        ):
            result = broker.place_market_order("ETH-USD", "buy", 50.0)

        self.assertEqual(result["status"], "unfilled")
        self.assertEqual(result["error"], "INSUFFICIENT_FUND")


if __name__ == "__main__":
    unittest.main()
