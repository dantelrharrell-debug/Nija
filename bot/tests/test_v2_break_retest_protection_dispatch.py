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


if __name__ == "__main__":
    unittest.main()
