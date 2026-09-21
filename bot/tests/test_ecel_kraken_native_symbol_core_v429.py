import unittest

from bot.ecel_execution_compiler import CompileRequest, ContractSchemaMap, ECELExecutionCompiler


class TestKrakenNativeSymbolCoreV429(unittest.TestCase):
    def test_known_kraken_legacy_ids_normalize_to_existing_contracts(self):
        cases = {
            "XETHZUSD": "ETH-USD",
            "XXBTZUSD": "XBT-USD",
            "XXRPZUSD": "XRP-USD",
        }
        schema = ContractSchemaMap()
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                normalized = ECELExecutionCompiler._normalize_symbol(raw, "kraken")
                self.assertEqual(normalized, expected)
                self.assertIsNotNone(
                    schema.get_rule("kraken", normalized),
                    "legacy alias must reuse an existing canonical ECEL contract",
                )

    def test_xethzusd_compiles_against_existing_eth_rule(self):
        compiler = ECELExecutionCompiler()
        compiler.schema._live_refresh_enabled = False
        result = compiler.compile(
            CompileRequest(
                broker="kraken",
                symbol="XETHZUSD",
                side="buy",
                order_type="MARKET",
                desired_notional_usd=28.75,
                price_hint_usd=2500.0,
            )
        )
        self.assertTrue(result.accepted, result.reason)
        self.assertEqual(result.symbol, "ETH-USD")
        self.assertEqual(result.rule.symbol, "ETH-USD")

    def test_unknown_kraken_native_id_remains_fail_closed(self):
        compiler = ECELExecutionCompiler()
        compiler.schema._live_refresh_enabled = False
        result = compiler.compile(
            CompileRequest(
                broker="kraken",
                symbol="XFOOZUSD",
                side="buy",
                order_type="MARKET",
                desired_notional_usd=28.75,
                price_hint_usd=1.0,
            )
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "NO_CONTRACT_RULE")

    def test_kraken_mapping_does_not_leak_to_other_brokers(self):
        self.assertEqual(
            ECELExecutionCompiler._normalize_symbol("XETHZUSD", "coinbase"),
            "XETHZ-USD",
        )


if __name__ == "__main__":
    unittest.main()
