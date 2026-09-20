from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from bot.multi_broker_execution_router import MultiBrokerExecutionRouter, RouteRequest


class TestBreakRetestProtectionDispatch(unittest.TestCase):
    def test_break_retest_entry_fails_before_any_broker_dispatch(self):
        router = MultiBrokerExecutionRouter()
        broker = MagicMock()
        broker.broker_type = "coinbase"
        broker.NAME = "coinbase"
        broker.supports_atomic_protected_entry = False

        request = RouteRequest(
            strategy="BREAK_RETEST",
            symbol="BTC-USD",
            side="buy",
            size_usd=25.0,
            preferred_broker="coinbase",
            metadata={
                "broker_client": broker,
                "broker_name": "coinbase",
                "intent_type": "entry",
                "protection_required": True,
                "stop_loss_pct": 0.01,
                "take_profit_pct": 0.02,
            },
        )

        result = router.route(request)

        self.assertFalse(result.success)
        self.assertEqual(result.error, "BREAK_RETEST_PROTECTION_DISPATCH_UNAVAILABLE")
        broker.place_market_order.assert_not_called()
        broker.execute_order.assert_not_called()
        broker.place_order.assert_not_called()

    def test_atomic_protected_broker_dispatches_with_sl_tp(self):
        router = MultiBrokerExecutionRouter()

        class AtomicProtectedBroker:
            broker_type = "coinbase"
            NAME = "coinbase"
            supports_atomic_protected_entry = True

            def __init__(self):
                self.calls = []

            def place_market_order_with_protection(
                self,
                symbol,
                side,
                quantity,
                *,
                size_type="quote",
                stop_loss_pct=None,
                take_profit_pct=None,
                protection_required=False,
            ):
                self.calls.append({
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "size_type": size_type,
                    "stop_loss_pct": stop_loss_pct,
                    "take_profit_pct": take_profit_pct,
                    "protection_required": protection_required,
                })
                return {
                    "status": "filled",
                    "order_id": "atomic-protected-1",
                    "filled_price": 101.0,
                    "filled_size_usd": float(quantity),
                }

        broker = AtomicProtectedBroker()
        request = RouteRequest(
            strategy="BREAK_RETEST",
            symbol="BTC-USD",
            side="buy",
            size_usd=25.0,
            preferred_broker="coinbase",
            metadata={
                "broker_client": broker,
                "broker_name": "coinbase",
                "intent_type": "entry",
                "protection_required": True,
                "stop_loss_pct": 0.01,
                "take_profit_pct": 0.02,
            },
        )

        self.assertTrue(router.supports_v2_protected_entry(request))
        result = router.route(request)

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(broker.calls), 1)
        call = broker.calls[0]
        self.assertEqual(call["stop_loss_pct"], 0.01)
        self.assertEqual(call["take_profit_pct"], 0.02)
        self.assertTrue(call["protection_required"])



if __name__ == "__main__":
    unittest.main()
