from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch


class _Keys:
    def __init__(self, credentials=None) -> None:
        self.credentials = credentials

    def get_user_api_key(self, user_id, broker_name):
        return self.credentials


class _UserConfig:
    def can_trade_pair(self, pair):
        return True

    def validate_position_size(self, size_usd):
        return True, None

    def get(self, key, default=None):
        return default


class _Config:
    def get_user_config(self, user_id):
        return _UserConfig()


class _Controls:
    def __init__(self) -> None:
        self.errors = 0

    def can_trade(self, user_id):
        return True, None

    def check_daily_trade_limit(self, user_id):
        return True, None

    def validate_position_size(self, user_id, position_size_usd, account_balance):
        return True, None

    def check_daily_loss_limit(self, user_id, max_daily_loss):
        return True, None

    def record_api_error(self, user_id):
        self.errors += 1


class _Client:
    def __init__(self, balance=100.0, order_result=None) -> None:
        self.balance = balance
        self.order_result = order_result or {"success": True, "status": "filled", "order_id": "o-1"}

    def get_account_balance(self):
        return {"total_balance": self.balance}

    def place_order(self, **kwargs):
        return dict(self.order_result)

    def get_positions(self):
        return []

    def close_position(self, pair):
        return {"success": True, "status": "filled", "order_id": "c-1"}


class FutureBrokerAdapterContractV65Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("execution.broker_adapter")
        for name in self.mod.registered_broker_client_factories():
            self.mod.unregister_broker_client_factory(name)
        self.controls = _Controls()

    def _adapter(self, credentials=None):
        patches = (
            patch.object(self.mod, "get_api_key_manager", return_value=_Keys(credentials)),
            patch.object(self.mod, "get_config_manager", return_value=_Config()),
            patch.object(self.mod, "get_hard_controls", return_value=self.controls),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return self.mod.SecureBrokerAdapter("user-1", "futurebroker")

    def test_missing_factory_never_fakes_balance_or_success(self) -> None:
        adapter = self._adapter(credentials={"key": "present"})
        self.assertFalse(adapter.execution_ready)
        balance = adapter.get_account_balance()
        self.assertFalse(balance["verified"])
        self.assertEqual(balance["total_balance"], 0.0)
        result = adapter.place_order("BTC-USD", "buy", 25.0)
        self.assertFalse(result["success"])

    def test_registered_factory_routes_real_client(self) -> None:
        self.mod.register_broker_client_factory(
            "futurebroker",
            lambda user_id, credentials: _Client(balance=123.45),
        )
        adapter = self._adapter(credentials={"key": "present"})
        self.assertTrue(adapter.execution_ready)
        self.assertAlmostEqual(adapter.get_account_balance()["total_balance"], 123.45)
        result = adapter.place_order("BTC-USD", "buy", 25.0)
        self.assertTrue(result["success"])
        self.assertEqual(result["broker"], "futurebroker")
        self.assertEqual(result["user_id"], "user-1")

    def test_ambiguous_timeout_response_is_not_promoted_to_success(self) -> None:
        self.mod.register_broker_client_factory(
            "futurebroker",
            lambda user_id, credentials: _Client(
                balance=100.0,
                order_result={"status": "unknown", "error": "timeout"},
            ),
        )
        adapter = self._adapter(credentials={"key": "present"})
        result = adapter.place_order("BTC-USD", "buy", 25.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
