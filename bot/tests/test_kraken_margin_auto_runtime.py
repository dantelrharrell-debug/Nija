from __future__ import annotations

import os
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.kraken_margin_engine import (
    HARD_MAX_LEVERAGE,
    KrakenMarginEngine,
    get_margin_engine,
    reset_margin_engines_for_tests,
)
from bot.kraken_margin_auto_runtime_patch import _patch_capability_matrix, _patch_router


class FakeKrakenAdapter:
    NAME = "Kraken"

    def __init__(self, account_id: str = "platform", *, pair_leverages=(2, 3), margin_level=500.0):
        self.account_identifier = account_id
        self.pair_leverages = list(pair_leverages)
        self.margin_level = float(margin_level)
        self.private_calls = []
        self.public_calls = []
        self.submit_calls = []
        self.api = SimpleNamespace(query_public=self.query_public)

    def query_public(self, method, params=None):
        self.public_calls.append((method, dict(params or {})))
        if method == "AssetPairs":
            return {
                "error": [],
                "result": {
                    "XXBTZUSD": {
                        "leverage_buy": list(self.pair_leverages),
                        "leverage_sell": list(self.pair_leverages),
                    }
                },
            }
        return {"error": ["not mocked"], "result": {}}

    def _kraken_api_call(self, method, params=None):
        self.private_calls.append((method, dict(params or {})))
        if method == "OpenPositions":
            return {"error": [], "result": {}}
        if method == "TradeBalance":
            return {
                "error": [],
                "result": {
                    "eb": "100.00",
                    "tb": "100.00",
                    "ml": str(self.margin_level),
                    "mo": "20.00" if self.margin_level > 0 else "0.00",
                    "mf": "80.00",
                    "n": "0.00",
                    "e": "100.00",
                },
            }
        return {"error": ["not mocked"], "result": {}}

    def place_market_order(self, symbol, side, size, **kwargs):
        self.submit_calls.append((symbol, side, size, dict(kwargs)))
        return {
            "status": "filled",
            "order_id": "margin-order-1",
            "filled_price": 50_000.0,
            "filled_size_usd": float(size),
        }


class TestAccountScopedMarginEngine(unittest.TestCase):
    def setUp(self):
        reset_margin_engines_for_tests()
        self.env = patch.dict(
            os.environ,
            {
                "NIJA_KRAKEN_MARGIN_ENABLED": "true",
                "NIJA_KRAKEN_AUTO_MARGIN_ENABLED": "true",
                "NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE": "2",
                "NIJA_KRAKEN_AUTO_MARGIN_LONG_ONLY": "true",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_engines_do_not_leak_permission_across_accounts(self):
        platform = get_margin_engine("platform")
        user = get_margin_engine("daivon")
        self.assertIsNot(platform, user)
        adapter = FakeKrakenAdapter("platform")
        self.assertEqual(platform.check_permissions(adapter).value, "CONFIRMED")
        self.assertEqual(user._permission_state.value, "UNKNOWN")

    def test_pair_discovery_uses_public_api_not_private_nonce_path(self):
        adapter = FakeKrakenAdapter(pair_leverages=(2, 3))
        engine = KrakenMarginEngine("platform", adapter=adapter)
        values = engine.get_pair_leverages("BTC-USD", "buy", adapter=adapter)
        self.assertEqual(values, (2, 3))
        self.assertEqual(adapter.public_calls[0][0], "AssetPairs")
        self.assertFalse(any(method == "AssetPairs" for method, _ in adapter.private_calls))

    def test_eligible_entry_is_planned_at_two_times(self):
        adapter = FakeKrakenAdapter(pair_leverages=(2, 3), margin_level=500.0)
        engine = KrakenMarginEngine("platform", adapter=adapter)
        plan = engine.plan_auto_margin(
            adapter=adapter,
            symbol="BTC-USD",
            side="buy",
            spot_size_usd=20.0,
            account_equity_usd=100.0,
        )
        self.assertTrue(plan.allowed)
        self.assertEqual(plan.leverage, 2)
        self.assertAlmostEqual(plan.leveraged_notional_usd, 40.0)
        self.assertLessEqual(plan.leverage, HARD_MAX_LEVERAGE)
        self.assertFalse(plan.reduce_only)

    def test_pair_without_two_times_remains_spot(self):
        adapter = FakeKrakenAdapter(pair_leverages=())
        engine = KrakenMarginEngine("platform", adapter=adapter)
        plan = engine.plan_auto_margin(
            adapter=adapter,
            symbol="BTC-USD",
            side="buy",
            spot_size_usd=20.0,
            account_equity_usd=100.0,
        )
        self.assertFalse(plan.allowed)
        self.assertIn("pair_leverage_unavailable", plan.reason)

    def test_low_margin_blocks_new_entry(self):
        adapter = FakeKrakenAdapter(pair_leverages=(2,), margin_level=150.0)
        engine = KrakenMarginEngine("platform", adapter=adapter)
        plan = engine.plan_auto_margin(
            adapter=adapter,
            symbol="BTC-USD",
            side="buy",
            spot_size_usd=20.0,
            account_equity_usd=100.0,
        )
        self.assertFalse(plan.allowed)
        self.assertIn("maintenance_low", plan.reason)

    def test_ten_times_is_clamped_to_three_times(self):
        engine = KrakenMarginEngine("platform")
        params = engine.build_order_margin_params(10)
        self.assertEqual(params["leverage"], "3")


class TestKrakenMarginDispatchBridge(unittest.TestCase):
    def setUp(self):
        reset_margin_engines_for_tests()
        self.env = patch.dict(
            os.environ,
            {
                "NIJA_KRAKEN_MARGIN_ENABLED": "true",
                "NIJA_KRAKEN_AUTO_MARGIN_ENABLED": "true",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    @staticmethod
    def _router_class():
        class MultiBrokerExecutionRouter:
            @staticmethod
            def _dispatch_direct_broker_market_order(broker, *, symbol, side, size_usd, metadata):
                return 1.0, float(size_usd)
        return MultiBrokerExecutionRouter

    def test_router_passes_leverage_and_reduce_only_without_margin_mode(self):
        adapter = FakeKrakenAdapter("platform", pair_leverages=(2, 3))
        module = types.ModuleType("bot.multi_broker_execution_router")
        module.MultiBrokerExecutionRouter = self._router_class()
        self.assertTrue(_patch_router(module))
        result = module.MultiBrokerExecutionRouter._dispatch_direct_broker_market_order(
            adapter,
            symbol="BTC-USD",
            side="buy",
            size_usd=40.0,
            metadata={
                "account_id": "platform",
                "leverage": 2,
                "reduce_only": False,
                "margin_mode": "cross",
                "price_hint_usd": 50_000.0,
            },
        )
        self.assertEqual(result, (50_000.0, 40.0))
        self.assertEqual(len(adapter.submit_calls), 1)
        _, _, _, kwargs = adapter.submit_calls[0]
        self.assertEqual(kwargs["leverage"], 2)
        self.assertFalse(kwargs["reduce_only"])
        self.assertIsNone(kwargs["margin_mode"])

    def test_margin_failure_does_not_fallback_to_spot(self):
        adapter = FakeKrakenAdapter("platform", pair_leverages=())
        module = types.ModuleType("bot.multi_broker_execution_router.failure")
        module.MultiBrokerExecutionRouter = self._router_class()
        self.assertTrue(_patch_router(module))
        with self.assertRaises(RuntimeError):
            module.MultiBrokerExecutionRouter._dispatch_direct_broker_market_order(
                adapter,
                symbol="BTC-USD",
                side="buy",
                size_usd=40.0,
                metadata={"account_id": "platform", "leverage": 2, "reduce_only": False},
            )
        self.assertEqual(adapter.submit_calls, [])


class TestKrakenMarginCapabilityInstall(unittest.TestCase):
    def test_margin_capability_is_added_with_three_times_ceiling(self):
        from bot import exchange_capabilities as cap_module
        self.assertTrue(_patch_capability_matrix(cap_module))
        row = cap_module.EXCHANGE_CAPABILITIES.get_capabilities(
            "kraken", cap_module.MarketMode.MARGIN
        )
        self.assertIsNotNone(row)
        self.assertTrue(row.supports_margin)
        self.assertTrue(row.supports_leverage)
        self.assertEqual(row.max_leverage, 3.0)


if __name__ == "__main__":
    unittest.main()
