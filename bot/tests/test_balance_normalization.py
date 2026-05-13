"""Regression tests for dict-based broker balance payload normalization."""

import unittest
from typing import Any, Dict, Optional

from bot.broker_manager import AccountType, BaseBroker, BrokerType
from bot.multi_account_broker_manager import MultiAccountBrokerManager


class DictBalanceBroker(BaseBroker):
    """Test broker returning dict-shaped balances."""

    def __init__(
        self,
        broker_type: BrokerType,
        account_type: AccountType,
        user_id: Optional[str] = None,
        balance: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(broker_type, account_type, user_id)
        self.connected = True
        self._balance = balance or {"available_balance": {"value": "0.0"}}

    def connect(self):
        self.connected = True
        return True

    def get_account_balance(self):
        return self._balance

    def get_positions(self):
        return []

    def place_market_order(
        self,
        symbol,
        side,
        quantity,
        size_type="quote",
        ignore_balance=False,
        ignore_min_trade=False,
        force_liquidate=False,
    ):
        return {"status": "filled", "symbol": symbol, "side": side, "quantity": quantity}


class TestBalanceNormalization(unittest.TestCase):
    def test_normalize_balance_value_supports_nested_balance_dict(self):
        manager = MultiAccountBrokerManager()
        value = manager._normalize_balance_value({"available_balance": {"value": "42.5"}})
        self.assertEqual(value, 42.5)

    def test_normalize_balance_value_supports_nested_total_key(self):
        manager = MultiAccountBrokerManager()
        value = manager._normalize_balance_value({"available_balance": {"total": "31.25"}})
        self.assertEqual(value, 31.25)

    def test_normalize_balance_value_handles_custom_nested_keys(self):
        manager = MultiAccountBrokerManager()
        value = manager._normalize_balance_value({"available_balance": {"balance_value": "19.75"}})
        self.assertEqual(value, 19.75)

    def test_aggregated_breakdown_counts_dict_balances(self):
        manager = MultiAccountBrokerManager()

        platform_coinbase = DictBalanceBroker(
            BrokerType.COINBASE,
            AccountType.PLATFORM,
            balance={"available_balance": {"value": "120.0"}},
        )
        user_coinbase = DictBalanceBroker(
            BrokerType.COINBASE,
            AccountType.USER,
            user_id="alice",
            balance={"total_balance": "35.0"},
        )

        manager._platform_brokers[BrokerType.COINBASE] = platform_coinbase
        manager.user_brokers["alice"] = {BrokerType.COINBASE: user_coinbase}

        breakdown = manager.get_aggregated_balance_breakdown(include_all_subaccounts=True)

        self.assertEqual(breakdown["coinbase"], 155.0)
        self.assertEqual(breakdown["platform_total"], 120.0)
        self.assertEqual(breakdown["user_total"], 35.0)
        self.assertEqual(breakdown["total_balance"], 155.0)


if __name__ == "__main__":
    unittest.main()
