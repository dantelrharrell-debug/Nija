from __future__ import annotations

import os
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import kraken_live_completion_v415_patch as v415


class _KrakenBroker:
    broker_type = "kraken"
    credentials_configured = True
    connected = True

    def _convert_to_kraken_symbol(self, symbol: str) -> str:
        normalized = symbol.upper().replace("/", "-").replace("_", "-")
        if normalized in {"ETH-USD", "XETHZUSD"}:
            return "XETHZUSD"
        if normalized in {"BTC-USD", "XXBTZUSD"}:
            return "XXBTZUSD"
        return normalized.replace("-", "")


class KrakenLiveCompletionV415Tests(unittest.TestCase):
    def _floor_env(self):
        return patch.dict(
            os.environ,
            {
                "KRAKEN_MIN_NOTIONAL_USD": "23.00",
                "NIJA_KRAKEN_MIN_NOTIONAL_USD": "23.00",
                "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD": "23.00",
                "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD": "23.00",
                "NIJA_KRAKEN_PAIR_MIN_BASE_BUFFER_PCT": "0.03",
            },
            clear=False,
        )

    def test_eth_required_quote_respects_base_minimum(self):
        with self._floor_env():
            required, details = v415._pair_required_quote(
                "ETH-USD",
                2625.51,
                _KrakenBroker(),
            )

        self.assertEqual(details["pair"], "XETHZUSD")
        self.assertAlmostEqual(details["min_base"], 0.01, places=8)
        self.assertGreater(float(required), 26.25)
        self.assertGreater(float(required), 23.00)

    def test_router_blocks_undersized_kraken_buy_before_dispatch(self):
        calls = {"count": 0}

        class FakeRouter:
            def _resolve_live_broker(self, broker_name: str):
                return _KrakenBroker()

            def _dispatch_via_inner_router(self, *args, **kwargs):
                calls["count"] += 1
                return 2625.51, float(kwargs.get("size_usd", 0.0))

        module = types.ModuleType("bot.multi_broker_execution_router")
        module.MultiBrokerExecutionRouter = FakeRouter
        module._InternalDispatchFailure = RuntimeError
        self.assertTrue(v415._patch_router(module))

        router = FakeRouter()
        with self._floor_env(), self.assertRaisesRegex(
            RuntimeError,
            "KRAKEN_PAIR_MINIMUM_PRE_DISPATCH_BLOCKED",
        ):
            router._dispatch_via_inner_router(
                symbol="ETH-USD",
                side="buy",
                size_usd=20.0,
                broker_name="kraken",
                metadata={
                    "broker_client": _KrakenBroker(),
                    "price_hint_usd": 2625.51,
                },
            )

        self.assertEqual(calls["count"], 0)

    def test_router_allows_executable_kraken_buy_without_upsizing(self):
        seen = {}

        class FakeRouter:
            def _dispatch_via_inner_router(self, *args, **kwargs):
                seen["size_usd"] = kwargs["size_usd"]
                return 2625.51, kwargs["size_usd"]

        module = types.ModuleType("bot.multi_broker_execution_router")
        module.MultiBrokerExecutionRouter = FakeRouter
        module._InternalDispatchFailure = RuntimeError
        self.assertTrue(v415._patch_router(module))

        with self._floor_env():
            result = FakeRouter()._dispatch_via_inner_router(
                symbol="ETH-USD",
                side="buy",
                size_usd=30.0,
                broker_name="kraken",
                metadata={
                    "broker_client": _KrakenBroker(),
                    "price_hint_usd": 2625.51,
                },
            )

        self.assertEqual(result, (2625.51, 30.0))
        self.assertEqual(seen["size_usd"], 30.0)

    def test_router_does_not_apply_buy_minimum_to_sell_exit(self):
        calls = {"count": 0}

        class FakeRouter:
            def _dispatch_via_inner_router(self, *args, **kwargs):
                calls["count"] += 1
                return 2625.51, kwargs["size_usd"]

        module = types.ModuleType("bot.multi_broker_execution_router")
        module.MultiBrokerExecutionRouter = FakeRouter
        module._InternalDispatchFailure = RuntimeError
        self.assertTrue(v415._patch_router(module))

        with self._floor_env():
            result = FakeRouter()._dispatch_via_inner_router(
                symbol="ETH-USD",
                side="sell",
                size_usd=5.0,
                broker_name="kraken",
                metadata={
                    "broker_client": _KrakenBroker(),
                    "price_hint_usd": 2625.51,
                    "intent_type": "exit",
                    "closing_position": True,
                },
            )

        self.assertEqual(result, (2625.51, 5.0))
        self.assertEqual(calls["count"], 1)

    def test_unconfigured_user_openpositions_is_blocked_without_private_io(self):
        calls = {"count": 0}

        def original(broker, *, account="", force=False):
            calls["count"] += 1
            return True, {"unexpected": {}}, "unexpected"

        module = types.ModuleType(
            "bot.runtime_kraken_margin_canonical_coverage_v366_patch"
        )
        module.fetch_margin_positions = original
        self.assertTrue(v415._patch_v366(module))

        broker = types.SimpleNamespace(
            credentials_configured=False,
            connected=False,
        )
        result = module.fetch_margin_positions(
            broker,
            account="user:test:kraken",
            force=True,
        )

        self.assertEqual(result, (False, {}, "credentials_not_configured"))
        self.assertEqual(calls["count"], 0)

    def test_disconnected_configured_user_openpositions_is_blocked_without_private_io(self):
        calls = {"count": 0}

        def original(broker, *, account="", force=False):
            calls["count"] += 1
            return True, {}, "unexpected"

        module = types.ModuleType(
            "bot.runtime_kraken_margin_canonical_coverage_v366_patch"
        )
        module.fetch_margin_positions = original
        self.assertTrue(v415._patch_v366(module))

        broker = types.SimpleNamespace(
            credentials_configured=True,
            connected=False,
        )
        result = module.fetch_margin_positions(
            broker,
            account="user:test:kraken",
        )

        self.assertEqual(result, (False, {}, "disconnected"))
        self.assertEqual(calls["count"], 0)

    def test_platform_openpositions_behavior_is_not_replaced(self):
        calls = {"count": 0}

        def original(broker, *, account="", force=False):
            calls["count"] += 1
            return True, {"platform": {}}, "original"

        module = types.ModuleType(
            "bot.runtime_kraken_margin_canonical_coverage_v366_patch"
        )
        module.fetch_margin_positions = original
        self.assertTrue(v415._patch_v366(module))

        broker = types.SimpleNamespace(
            credentials_configured=False,
            connected=False,
        )
        result = module.fetch_margin_positions(
            broker,
            account="platform:kraken",
        )

        self.assertEqual(result, (True, {"platform": {}}, "original"))
        self.assertEqual(calls["count"], 1)

    def test_sitecustomize_requests_v415_install(self):
        source = (
            Path(__file__).resolve().parents[2] / "sitecustomize.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _install_kraken_live_completion_v415()", source)
        self.assertIn("_install_kraken_live_completion_v415()", source)
        self.assertIn("kraken_live_completion_v415_patch.py", source)


if __name__ == "__main__":
    unittest.main()
