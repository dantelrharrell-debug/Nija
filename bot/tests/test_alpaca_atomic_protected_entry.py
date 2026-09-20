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
    def __init__(self, *, include_take_profit: bool = True, include_stop_loss: bool = True):
        self.include_take_profit = include_take_profit
        self.include_stop_loss = include_stop_loss
        self.submit_calls = []
        self.read_calls = []

    def submit_order(self, order_data):
        self.submit_calls.append(order_data)
        return SimpleNamespace(
            id="alpaca-parent-1",
            status=_enum("accepted"),
            order_class=_enum("bracket"),
            filled_avg_price=None,
            legs=None,
        )

    def get_order_by_id(self, order_id, filter_request):
        self.read_calls.append((order_id, filter_request))
        legs = []
        if self.include_take_profit:
            legs.append(
                SimpleNamespace(
                    id="alpaca-tp-1",
                    limit_price="102.00",
                    stop_price=None,
                )
            )
        if self.include_stop_loss:
            legs.append(
                SimpleNamespace(
                    id="alpaca-sl-1",
                    limit_price=None,
                    stop_price="99.00",
                )
            )
        return SimpleNamespace(
            id=order_id,
            status=_enum("accepted"),
            order_class=_enum("bracket"),
            filled_avg_price=None,
            legs=legs,
        )


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
    broker.get_candles = lambda *args, **kwargs: [{"close": 100.0}]
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

    def test_single_bracket_submission_verifies_both_legs(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        guard1, guard2, guard3 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
        ):
            result = broker.place_market_order_with_protection(
                "SPY",
                "buy",
                250.0,
                size_type="quote",
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
                protection_required=True,
                decision_trace_id="trace-1",
            )

        self.assertTrue(result["protection_verified"], result)
        self.assertEqual(result["order_id"], "alpaca-parent-1")
        self.assertEqual(result["take_profit_order_id"], "alpaca-tp-1")
        self.assertEqual(result["stop_loss_order_id"], "alpaca-sl-1")
        self.assertEqual(result["take_profit_price"], 102.0)
        self.assertEqual(result["stop_loss_price"], 99.0)
        self.assertEqual(len(api.submit_calls), 1)
        order_data = api.submit_calls[0]
        self.assertEqual(float(order_data.qty), 2.0)
        self.assertEqual(order_data.order_class.value, "bracket")
        self.assertEqual(float(order_data.take_profit.limit_price), 102.0)
        self.assertEqual(float(order_data.stop_loss.stop_price), 99.0)
        self.assertGreaterEqual(len(api.read_calls), 1)

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
                "price_hint_usd": 100.0,
                "decision_trace_id": "trace-router-1",
            },
        )
        guard1, guard2, guard3 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
        ):
            self.assertTrue(router.supports_v2_protected_entry(request))
            result = router.route(request)

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(api.submit_calls), 1)
        self.assertEqual(float(result.filled_size_usd), 200.0)

    def test_missing_stop_leg_never_claims_verified_protection(self):
        api = _FakeAlpacaAPI(include_stop_loss=False)
        broker = _broker(api)
        guard1, guard2, guard3 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
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
        self.assertEqual(result["error"], "PROTECTED_ENTRY_VERIFICATION_FAILED")
        self.assertEqual(len(api.submit_calls), 1)

    def test_quote_size_below_one_share_fails_before_submit(self):
        api = _FakeAlpacaAPI()
        broker = _broker(api)
        guard1, guard2, guard3 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
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
        guard1, guard2, guard3 = self._guards()
        with (
            patch.dict(os.environ, {"NIJA_ENABLE_ALPACA_PROTECTED_ENTRY": "true"}),
            guard1,
            guard2,
            guard3,
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
