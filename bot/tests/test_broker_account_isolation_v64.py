from __future__ import annotations

import importlib
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch


class _Broker:
    def __init__(self, name: str, balance: float, account_identifier: str = "platform") -> None:
        self.broker_type = types.SimpleNamespace(value=name)
        self._last_known_balance = balance
        self.account_identifier = account_identifier
        self.connected = True


class BrokerAccountIsolationV64Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.broker_account_isolation_v64_patch")
        self.mod._USER_SCOPE_STATE.clear()
        self.mod._SCOPE_DAILY_PNL.clear()
        self.mod._PLATFORM_BREAKER = None

    def test_account_drawdown_is_isolated_by_account(self) -> None:
        level, _mult, halted, _reason = self.mod._user_scope_drawdown(
            "account:alpha:coinbase", 100.0
        )
        self.assertEqual(level, "CLEAR")
        self.assertFalse(halted)

        level, _mult, halted, _reason = self.mod._user_scope_drawdown(
            "account:alpha:coinbase", 70.0
        )
        self.assertEqual(level, "HALT")
        self.assertTrue(halted)

        level, _mult, halted, _reason = self.mod._user_scope_drawdown(
            "account:beta:coinbase", 100.0
        )
        self.assertEqual(level, "CLEAR")
        self.assertFalse(halted)

    def test_platform_scope_does_not_mix_broker_balances(self) -> None:
        class _Decision:
            level = types.SimpleNamespace(value="CLEAR")
            allow_new_entries = True
            position_size_multiplier = 1.0
            drawdown_pct = 0.0

        class _Breaker:
            def __init__(self) -> None:
                self.initialized = None
                self.updated = []

            def initialise(self, starting_equity: float) -> None:
                self.initialized = starting_equity

            def update_equity(self, equity: float):
                self.updated.append(equity)
                return _Decision()

        fake_module = types.ModuleType("bot.global_drawdown_circuit_breaker")
        fake_module.GlobalDrawdownCircuitBreaker = _Breaker

        with patch.object(
            self.mod,
            "_canonical_platform_equity",
            return_value=(True, 240.08, 2, "canonical_capital_authority"),
        ), patch.dict(sys.modules, {"bot.global_drawdown_circuit_breaker": fake_module}):
            level, mult, halted, reason = self.mod._platform_scope_drawdown(95.12)

        self.assertEqual(level, "CLEAR")
        self.assertEqual(mult, 1.0)
        self.assertFalse(halted)
        self.assertEqual(reason, "")
        self.assertEqual(self.mod._PLATFORM_BREAKER.initialized, 240.08)
        self.assertEqual(self.mod._PLATFORM_BREAKER.updated, [240.08])

    def test_scope_for_user_and_platform_brokers(self) -> None:
        scope, platform = self.mod._scope_for_broker(_Broker("okx", 145.0))
        self.assertEqual(scope, "platform")
        self.assertTrue(platform)

        scope, platform = self.mod._scope_for_broker(
            _Broker("kraken", 80.0, account_identifier="user-7")
        )
        self.assertEqual(scope, "account:user-7:kraken")
        self.assertFalse(platform)

    def test_shared_strategy_cycles_are_serialized_and_broker_local(self) -> None:
        fake_module = types.ModuleType("trading_strategy_v64_fake")
        calls: list[tuple[str, float]] = []
        active = 0
        max_active = 0
        state_lock = threading.Lock()

        class _Apex:
            def __init__(self) -> None:
                self.broker_client = None
                self._last_account_balance = 999.0
                self.execution_engine = types.SimpleNamespace(broker_client=None)

            def update_broker_client(self, broker) -> None:
                self.broker_client = broker
                self.execution_engine.broker_client = broker

        class _Strategy:
            def __init__(self) -> None:
                self.apex = _Apex()
                self.broker = None

            def _broker_entry_balance(self, broker) -> float:
                return float(broker._last_known_balance)

            def run_cycle(self, broker=None, user_mode=False) -> int:
                nonlocal active, max_active
                with state_lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    calls.append(
                        (
                            str(self.apex.broker_client.broker_type.value),
                            float(self.apex._last_account_balance),
                        )
                    )
                    time.sleep(0.02)
                    return 120
                finally:
                    with state_lock:
                        active -= 1

        fake_module.TradingStrategy = _Strategy
        self.mod._patch_trading_strategy_module(fake_module)
        strategy = _Strategy()
        okx = _Broker("okx", 145.0)
        coinbase = _Broker("coinbase", 95.0)

        threads = [
            threading.Thread(target=strategy.run_cycle, kwargs={"broker": okx}),
            threading.Thread(target=strategy.run_cycle, kwargs={"broker": coinbase}),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(max_active, 1)
        self.assertCountEqual(calls, [("okx", 145.0), ("coinbase", 95.0)])
        self.assertEqual(strategy.apex._last_account_balance, 999.0)


if __name__ == "__main__":
    unittest.main()
