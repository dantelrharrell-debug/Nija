import sys
import types
import unittest
from unittest import mock

from bot import runtime_position_read_liveness_v342_patch as v342


class _Client:
    def __init__(self):
        self.price_calls = 0

    def get_portfolios(self):
        return {"portfolios": [{"type": "DEFAULT", "uuid": "pf-1"}]}

    def get_portfolio_breakdown(self, *, portfolio_uuid):
        assert portfolio_uuid == "pf-1"
        return {
            "breakdown": {
                "spot_positions": [
                    {
                        "asset": "BTC",
                        "total_balance_crypto": "0.001",
                        "total_balance_fiat": "78.50",
                    },
                    {
                        "asset": "ETH",
                        "total_balance_crypto": "0.000001",
                        "total_balance_fiat": "0.002",
                    },
                ]
            }
        }


class _CoinbaseBroker:
    def __init__(self):
        self.client = _Client()
        self.current_price_calls = 0

    def _api_call_with_retry(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def get_current_price(self, symbol):
        self.current_price_calls += 1
        raise AssertionError(f"unexpected market read for {symbol}")


class PositionReadLivenessV342Test(unittest.TestCase):
    def test_coinbase_uses_portfolio_fiat_without_market_fanout(self):
        broker = _CoinbaseBroker()
        rows = v342._coinbase_fast_positions(broker)
        self.assertEqual(1, len(rows))
        self.assertEqual("BTC-USD", rows[0]["symbol"])
        self.assertAlmostEqual(0.001, rows[0]["quantity"])
        self.assertAlmostEqual(78.50, rows[0]["size_usd"])
        self.assertAlmostEqual(78500.0, rows[0]["current_price"])
        self.assertEqual(0, broker.current_price_calls)

    def test_coinbase_accounts_fallback_keeps_positive_holdings_without_price_calls(self):
        class Client:
            def get_accounts(self):
                return {
                    "accounts": [
                        {"currency": "ORCA", "available_balance": {"value": "3.0"}},
                        {"currency": "USD", "available_balance": {"value": "25"}},
                    ]
                }

        broker = _CoinbaseBroker()
        broker.client = Client()
        rows = v342._coinbase_fast_positions(broker)
        self.assertEqual(["ORCA-USD"], [row["symbol"] for row in rows])
        self.assertEqual(0.0, rows[0]["current_price"])
        self.assertEqual(0.0, rows[0]["size_usd"])
        self.assertEqual(0, broker.current_price_calls)

    def test_kraken_patch_reuses_only_v312_fresh_observation(self):
        calls = {"original": 0}

        def original(broker, call):
            calls["original"] += 1
            return call()

        fake_v299 = types.ModuleType("bot.runtime_kraken_credential_read_convergence_v299_patch")
        fake_v299._credential_balance_call = original
        fake_v312 = types.ModuleType("bot.runtime_kraken_balance_epoch_handoff_v312_patch")
        fake_v312._fresh_observation = lambda broker, not_before=0.0: {
            "response": {"error": [], "result": {"ZUSD": "10.0"}},
            "age_s": 1.0,
        }

        with mock.patch.dict(sys.modules, {
            "bot.runtime_kraken_credential_read_convergence_v299_patch": fake_v299,
            "bot.runtime_kraken_balance_epoch_handoff_v312_patch": fake_v312,
        }, clear=False):
            self.assertTrue(v342._patch_kraken_stale_join())
            broker = types.SimpleNamespace(account_identifier="PLATFORM")
            result = fake_v299._credential_balance_call(
                broker,
                lambda: (_ for _ in ()).throw(AssertionError("duplicate private call")),
            )

        self.assertEqual("10.0", result["result"]["ZUSD"])
        self.assertEqual(0, calls["original"])

    def test_kraken_patch_falls_back_when_no_fresh_observation_exists(self):
        calls = {"original": 0, "private": 0}

        def original(broker, call):
            calls["original"] += 1
            return call()

        fake_v299 = types.ModuleType("bot.runtime_kraken_credential_read_convergence_v299_patch")
        fake_v299._credential_balance_call = original
        fake_v312 = types.ModuleType("bot.runtime_kraken_balance_epoch_handoff_v312_patch")
        fake_v312._fresh_observation = lambda broker, not_before=0.0: None

        with mock.patch.dict(sys.modules, {
            "bot.runtime_kraken_credential_read_convergence_v299_patch": fake_v299,
            "bot.runtime_kraken_balance_epoch_handoff_v312_patch": fake_v312,
        }, clear=False):
            self.assertTrue(v342._patch_kraken_stale_join())
            broker = types.SimpleNamespace(account_identifier="PLATFORM")

            def private_call():
                calls["private"] += 1
                return {"error": [], "result": {"ZUSD": "11.0"}}

            result = fake_v299._credential_balance_call(broker, private_call)

        self.assertEqual("11.0", result["result"]["ZUSD"])
        self.assertEqual(1, calls["original"])
        self.assertEqual(1, calls["private"])


if __name__ == "__main__":
    unittest.main()
