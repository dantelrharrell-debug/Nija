from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.broker_manager import AccountType, AlpacaBroker, BrokerType
from bot.multi_broker_execution_router import MultiBrokerExecutionRouter, RouteRequest


def _enum(value: str):
    return SimpleNamespace(value=value)


class _FakeAlpacaAPI:
    def __init__(
        self,
        *,
        include_take_profit: bool = True,
        include_stop_loss: bool = True,
        take_profit_status: str = "new",
        stop_loss_status: str = "new",
        parent_status: str = "filled",
        filled_qty: float = 2.0,
        filled_price: float = 100.0,
        read_sequence=None,
    ):
        self.include_take_profit = include_take_profit
        self.include_stop_loss = include_stop_loss
        self.take_profit_status = take_profit_status
        self.stop_loss_status = stop_loss_status
        self.parent_status = parent_status
        self.filled_qty = filled_qty
        self.filled_price = filled_price
        self.read_sequence = list(read_sequence or [])
        self.submit_calls = []
        self.read_calls = []
        self.cancel_calls = []
        self.cancel_requested = False

    def submit_order(self, order_data):
        self.submit_calls.append(order_data)
        return SimpleNamespace(
            id="alpaca-parent-1",
            status=_enum("accepted"),
            order_class=_enum("bracket"),
            filled_qty="0",
            filled_avg_price=None,
            legs=None,
        )

    def _snapshot(self, override=None):
        state = dict(override or {})
        include_tp = state.get("include_take_profit", self.include_take_profit)
        include_sl = state.get("include_stop_loss", self.include_stop_loss)
        parent_status = state.get("parent_status", self.parent_status)
        filled_qty = state.get("filled_qty", self.filled_qty)
        filled_price = state.get("filled_price", self.filled_price)
        tp_status = state.get("take_profit_status", self.take_profit_status)
        sl_status = state.get("stop_loss_status", self.stop_loss_status)

        if self.cancel_requested and not state:
            parent_status = "canceled"
            filled_qty = 0.0
            filled_price = 0.0
            include_tp = False
            include_sl = False

        legs = []
        if include_tp:
            legs.append(
                SimpleNamespace(
                    id="alpaca-tp-1",
                    status=_enum(tp_status),
                    limit_price="102.00",
                    stop_price=None,
                )
            )
        if include_sl:
            legs.append(
                SimpleNamespace(
                    id="alpaca-sl-1",
                    status=_enum(sl_status),
                    limit_price=None,
                    stop_price="99.00",
                )
            )
        return SimpleNamespace(
            id="alpaca-parent-1",
            status=_enum(parent_status),
            order_class=_enum("bracket"),
            filled_qty=str(filled_qty),
            filled_avg_price=str(filled_price) if filled_price else None,
            legs=legs,
        )

    def get_order_by_id(self, order_id, filter_request):
        self.read_calls.append((order_id, filter_request))
        if self.read_sequence:
            state = self.read_sequence.pop(0)
            return self._snapshot(state)
        return self._snapshot()

    def cancel_order_by_id(self, order_id):
        self.cancel_calls.append(order_id)
        self.cancel_requested = True
        return None


def _broker(api: _FakeAlpacaAPI) -> AlpacaBroker:
    broker = object.__new__(AlpacaBroker)
    broker.api = api
    broker._paper = False
    broker._api_key = "test"
    broker._api_secret = "test"
    broker.account_type = AccountType.PLATFORM
    broker.account_identifier = "PLATFORM"
    broker.broker_type = BrokerType.ALPACA
    broker.connected = True
    broker.is_market_open = lambda: True
    broker._alpaca_protected_reference_price = lambda *args, **kwargs: 100.0
    return broker


class TestAlpacaAtomicProtectedEntry(unittest.TestCase):
    def _guards(self):
        return (
            patch("bot.broker_manager._reject_if_unauthorized_order_submit", return_value=None),
            patch("bot.broker_manager._check_broker_isolation", return_value=None),
            patch(
                "bot.app_store_mode.get_app_store_mode",
                return_value=SimpleNamespace(is_enabled=lambda: False),
            ),
            patch("bot.broker_manager.time.sleep", return_value=None),
        )

    def _submit(self, broker, **kwargs):
        guard1, guard2, guard3, guard4 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
            guard4,
        ):
            return broker.place_market_order_with_protection(
                "SPY",
                "buy",
                250.0,
                size_type="quote",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
                protection_required=True,
                **kwargs,
            )

    def test_feature_flag_off_submits_nothing(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        with patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "false"}):
            result = broker.place_market_order_with_protection(
                "SPY",
                "buy",
                250.0,
                size_type="quote",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
                protection_required=True,
            )

        self.assertFalse(result["protection_verified"])
        self.assertEqual(result["error"], "ALPACA_PROTECTED_ENTRY_NOT_ENABLED")
        self.assertEqual(api.submit_calls, [])

    def test_single_bracket_submission_requires_real_fill_and_two_live_legs(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        result = self._submit(broker, decision_trace_id="trace-1")

        self.assertTrue(result["protection_verified"], result)
        self.assertEqual(result["status"], "filled")
        self.assertEqual(result["order_id"], "alpaca-parent-1")
        self.assertEqual(result["take_profit_order_id"], "alpaca-tp-1")
        self.assertEqual(result["stop_loss_order_id"], "alpaca-sl-1")
        self.assertEqual(result["take_profit_price"], 102.0)
        self.assertEqual(result["stop_loss_price"], 99.0)
        self.assertEqual(result["filled_price"], 100.0)
        self.assertEqual(result["filled_size_usd"], 200.0)
        self.assertEqual(len(api.submit_calls), 1)
        order_data = api.submit_calls[0]
        self.assertEqual(float(order_data.qty), 2.0)
        self.assertEqual(order_data.order_class.value, "bracket")
        self.assertEqual(float(order_data.take_profit.limit_price), 102.0)
        self.assertEqual(float(order_data.stop_loss.stop_price), 99.0)

    def test_partial_nested_readback_retries_until_both_legs_are_visible(self):
        api = _FakeAlpacaAPI(
            read_sequence=[
                {
                    "parent_status": "filled",
                    "filled_qty": 2.0,
                    "filled_price": 100.0,
                    "include_take_profit": True,
                    "include_stop_loss": False,
                },
                {
                    "parent_status": "filled",
                    "filled_qty": 2.0,
                    "filled_price": 100.0,
                    "include_take_profit": True,
                    "include_stop_loss": True,
                },
            ]
        )
        broker = _broker(api)
        result = self._submit(broker)

        self.assertTrue(result["protection_verified"], result)
        self.assertGreaterEqual(len(api.read_calls), 2)
        self.assertEqual(len(api.submit_calls), 1)

    def test_multi_router_dispatches_only_after_concrete_alpaca_leg_verification(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        router = MultiBrokerExecutionRouter()
        request = RouteRequest(
            strategy="BREAK_RETEST",
            symbol="SPY",
            side="buy",
            size_usd=250.0,
            preferred_broker="alpaca",
            metadata={
                "broker_client": broker,
                "broker_name": "alpaca",
                "intent_type": "entry",
                "protection_required": True,
                "stop_loss_pct": 0.01,
                "take_profit_pct": 0.02,
                "price_hint_usd": 999.0,
                "decision_trace_id": "trace-router-1",
            },
        )
        guard1, guard2, guard3, guard4 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
            guard4,
        ):
            self.assertTrue(router.supports_v2_protected_entry(request))
            result = router.route(request)

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(api.submit_calls), 1)
        self.assertEqual(float(result.fill_price), 100.0)
        self.assertEqual(float(result.filled_size_usd), 200.0)

    def test_missing_stop_leg_preserves_order_id_as_submission_uncertain(self):
        api = _FakeAlpacaAPI(include_stop_loss=False)
        broker = _broker(api)
        router = MultiBrokerExecutionRouter()
        request = RouteRequest(
            strategy="BREAK_RETEST",
            symbol="SPY",
            side="buy",
            size_usd=250.0,
            preferred_broker="alpaca",
            metadata={
                "broker_client": broker,
                "broker_name": "alpaca",
                "intent_type": "entry",
                "protection_required": True,
                "stop_loss_pct": 0.01,
                "take_profit_pct": 0.02,
            },
        )
        guard1, guard2, guard3, guard4 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
            guard4,
        ):
            result = router.route(request)

        self.assertFalse(result.success)
        self.assertEqual(result.order_id, "alpaca-parent-1")
        self.assertIn("PROTECTED_ENTRY_RECONCILIATION_REQUIRED", result.error or "")
        self.assertEqual(len(api.submit_calls), 1)

    def test_inactive_stop_leg_never_claims_verified_protection(self):
        api = _FakeAlpacaAPI(stop_loss_status="canceled")
        broker = _broker(api)
        result = self._submit(broker)

        self.assertFalse(result["protection_verified"])
        self.assertTrue(result["submission_uncertain"])
        self.assertEqual(result["order_id"], "alpaca-parent-1")

    def test_unfilled_parent_is_cancelled_and_zero_fill_confirmed(self):
        api = _FakeAlpacaAPI(
            parent_status="accepted",
            filled_qty=0.0,
            filled_price=0.0,
        )
        broker = _broker(api)
        result = self._submit(broker)

        self.assertFalse(result["protection_verified"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error"], "PROTECTED_ENTRY_CANCEL_CONFIRMED_ZERO_FILL")
        self.assertEqual(api.cancel_calls, ["alpaca-parent-1"])

    def test_app_store_guard_failure_fails_closed_before_submit(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            patch(
                "bot.app_store_mode.get_app_store_mode",
                side_effect=RuntimeError("guard unavailable"),
            ),
        ):
            result = broker.place_market_order_with_protection(
                "SPY",
                "buy",
                250.0,
                size_type="quote",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
                protection_required=True,
            )

        self.assertFalse(result["protection_verified"])
        self.assertIn("APP_STORE_GUARD_UNAVAILABLE", result["error"])
        self.assertEqual(api.submit_calls, [])

    def test_quote_size_below_one_share_fails_before_submit(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        guard1, guard2, guard3, guard4 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
            guard4,
        ):
            result = broker.place_market_order_with_protection(
                "SPY",
                "buy",
                50.0,
                size_type="quote",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
                protection_required=True,
            )

        self.assertFalse(result["protection_verified"])
        self.assertEqual(result["error"], "PROTECTED_ENTRY_REQUIRES_AT_LEAST_ONE_SHARE")
        self.assertEqual(api.submit_calls, [])

    def test_fractional_base_quantity_is_rejected_before_submit(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        guard1, guard2, guard3, guard4 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
            guard4,
        ):
            result = broker.place_market_order_with_protection(
                "SPY",
                "buy",
                1.5,
                size_type="base",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
                protection_required=True,
            )

        self.assertFalse(result["protection_verified"])
        self.assertEqual(result["error"], "PROTECTED_ENTRY_REQUIRES_WHOLE_SHARES")
        self.assertEqual(api.submit_calls, [])


if __name__ == "__main__":
    unittest.main()
