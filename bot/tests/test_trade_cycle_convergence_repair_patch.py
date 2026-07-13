from __future__ import annotations

import importlib.util
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch as env_patch


_PATCH_PATH = Path(__file__).resolve().parents[1] / "trade_cycle_convergence_repair_patch.py"
_SPEC = importlib.util.spec_from_file_location("trade_cycle_convergence_repair_patch_under_test", _PATCH_PATH)
assert _SPEC is not None and _SPEC.loader is not None
repair = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(repair)


class TradeCycleConvergenceRepairTests(unittest.TestCase):
    def test_classify_scan_result_emits_stable_terminal_outcomes(self) -> None:
        cases = [
            (SimpleNamespace(symbols_scored=8, entries_taken=1, entries_blocked=0, exits_taken=0), "ORDER_SUBMITTED"),
            (SimpleNamespace(symbols_scored=8, entries_taken=0, entries_blocked=1, exits_taken=0), "ENTRY_BLOCKED"),
            (
                SimpleNamespace(
                    symbols_scored=8,
                    entries_taken=0,
                    entries_blocked=1,
                    exits_taken=0,
                    reason="max positions reached",
                ),
                "MAX_POSITIONS_REACHED",
            ),
            (SimpleNamespace(symbols_scored=0, entries_taken=0, entries_blocked=0, exits_taken=0), "NO_MARKETS_OR_DATA"),
            (SimpleNamespace(symbols_scored=8, entries_taken=0, entries_blocked=0, exits_taken=0), "NO_SIGNAL"),
        ]
        for result, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(repair.classify_scan_result(result), expected)

    def test_position_adoption_verification_recovers_omitted_broker(self) -> None:
        expected_broker = object()

        class Strategy:
            def adopt_existing_positions(self, broker=None, broker_name="", account_id=""):
                return {"success": True, "positions_adopted": 0}

            def verify_position_adoption_status(self, broker, broker_name="", account_id=""):
                return broker is expected_broker and account_id == "USER_TEST_KRAKEN"

            def run_cycle(self, broker=None, user_mode=False):
                return 15

        repair._patch_trading_strategy_class(Strategy)
        strategy = Strategy()
        strategy.adopt_existing_positions(
            broker=expected_broker,
            broker_name="kraken",
            account_id="USER_TEST_KRAKEN",
        )
        self.assertTrue(
            strategy.verify_position_adoption_status(
                broker_name="kraken",
                account_id="USER_TEST_KRAKEN",
            )
        )

    def test_user_cycle_uses_broker_scoped_balance_and_independent_mode(self) -> None:
        platform_broker = SimpleNamespace(name="kraken-platform", _nija_last_account_balance_usd=225.04)
        user_broker = SimpleNamespace(
            name="kraken-user",
            account_id="USER_TEST",
            _nija_last_account_balance_usd=74.25,
        )

        class Apex:
            def __init__(self) -> None:
                self._last_account_balance = 225.04
                self.broker_client = platform_broker

            def update_broker_client(self, broker) -> None:
                self.broker_client = broker

        class Strategy:
            def __init__(self) -> None:
                self.broker = platform_broker
                self.apex = Apex()
                self.symbols = ["BTC-USD"]
                self.seen = None

            def run_cycle(self, broker=None, user_mode=False):
                self.seen = (broker, user_mode, self.apex._last_account_balance, self.apex.broker_client)
                return 17

        repair._patch_trading_strategy_class(Strategy)
        strategy = Strategy()
        with env_patch.dict(
            os.environ,
            {
                "NIJA_INDEPENDENT_USER_TRADING": "true",
                "NIJA_COPY_TRADE_ENABLED": "false",
            },
            clear=False,
        ):
            result = strategy.run_cycle(broker=user_broker, user_mode=True)

        self.assertEqual(result, 17)
        self.assertIs(strategy.seen[0], user_broker)
        self.assertFalse(strategy.seen[1])
        self.assertEqual(strategy.seen[2], 74.25)
        self.assertIs(strategy.seen[3], user_broker)
        self.assertIs(strategy.broker, platform_broker)
        self.assertEqual(strategy.apex._last_account_balance, 225.04)
        self.assertIs(strategy.apex.broker_client, platform_broker)

    def test_shared_strategy_cycles_are_serialized_across_accounts(self) -> None:
        broker_a = SimpleNamespace(name="kraken-a", account_id="ACCOUNT_A", _nija_last_account_balance_usd=50.0)
        broker_b = SimpleNamespace(name="kraken-b", account_id="ACCOUNT_B", _nija_last_account_balance_usd=60.0)

        class Apex:
            def __init__(self) -> None:
                self._last_account_balance = 0.0
                self.broker_client = None

            def update_broker_client(self, broker) -> None:
                self.broker_client = broker

        class Strategy:
            def __init__(self) -> None:
                self.broker = None
                self.apex = Apex()
                self.symbols = ["BTC-USD"]
                self.concurrent = 0
                self.max_concurrent = 0
                self.state_lock = threading.Lock()
                self.completed = []

            def run_cycle(self, broker=None, user_mode=False):
                with self.state_lock:
                    self.concurrent += 1
                    self.max_concurrent = max(self.max_concurrent, self.concurrent)
                time.sleep(0.04)
                with self.state_lock:
                    self.completed.append((broker, self.apex._last_account_balance))
                    self.concurrent -= 1
                return 11

        repair._patch_trading_strategy_class(Strategy)
        strategy = Strategy()
        errors = []

        def run(broker) -> None:
            try:
                strategy.run_cycle(broker=broker)
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = threading.Thread(target=run, args=(broker_a,))
        second = threading.Thread(target=run, args=(broker_b,))
        first.start()
        second.start()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(strategy.max_concurrent, 1)
        self.assertEqual({entry[1] for entry in strategy.completed}, {50.0, 60.0})

    def test_same_thread_reentry_is_skipped(self) -> None:
        broker = SimpleNamespace(name="kraken", account_id="ACCOUNT_A", _nija_last_account_balance_usd=50.0)

        class Apex:
            def __init__(self) -> None:
                self._last_account_balance = 0.0
                self.broker_client = None

            def update_broker_client(self, selected) -> None:
                self.broker_client = selected

        class Strategy:
            def __init__(self) -> None:
                self.broker = broker
                self.apex = Apex()
                self.symbols = ["BTC-USD"]
                self.nested_result = None

            def run_cycle(self, broker=None, user_mode=False):
                self.nested_result = self.run_cycle(broker=broker)
                return 20

        repair._patch_trading_strategy_class(Strategy)
        strategy = Strategy()
        self.assertEqual(strategy.run_cycle(broker=broker), 20)
        self.assertEqual(strategy.nested_result, 5)

    def test_balance_method_wrapper_caches_numeric_balance(self) -> None:
        class Broker:
            def get_account_balance(self):
                return {"total_balance": 88.75}

        repair._patch_balance_method(Broker)
        broker = Broker()
        self.assertEqual(broker.get_account_balance(), {"total_balance": 88.75})
        self.assertEqual(broker._nija_last_account_balance_usd, 88.75)
        self.assertGreater(broker._nija_last_account_balance_at, 0)


if __name__ == "__main__":
    unittest.main()
