"""Offline checks that credential diagnostics do not disclose provider inputs."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class BalanceDiagnosticRedactionTests(unittest.TestCase):
    """Exercise real diagnostic paths with synthetic inputs and no network."""

    def setUp(self):
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda: None
        path = Path(__file__).resolve().parents[1] / "fix_balance_detection.py"
        spec = importlib.util.spec_from_file_location("balance_diagnostic", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"dotenv": dotenv}):
            spec.loader.exec_module(self.module)

    def test_configured_keys_are_returned_but_never_printed(self):
        coinbase = "organizations/synthetic-private-owner/apiKeys/synthetic-key"
        kraken = "synthetic-private-kraken-identity"
        value = "synthetic-private-material"
        env = dict(COINBASE_API_KEY=coinbase, COINBASE_API_SECRET=value,
                   KRAKEN_PLATFORM_API_KEY=kraken, KRAKEN_PLATFORM_API_SECRET=value)
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(output):
            self.assertEqual(self.module.test_coinbase_credentials(), (True, coinbase, value))
            self.assertEqual(self.module.test_kraken_credentials(), (True, kraken, value))
        for marker in (coinbase[:40], kraken[:20], value):
            self.assertNotIn(marker, output.getvalue())

    def test_provider_exception_is_not_printed_or_returned(self):
        marker = "synthetic-sensitive-provider-error"
        rest = types.ModuleType("coinbase.rest")

        def reject(**kwargs):
            raise RuntimeError(marker)

        rest.RESTClient = reject
        client = types.SimpleNamespace(get_accounts=lambda: reject())
        output = io.StringIO()
        with patch.dict(sys.modules, {"coinbase": types.ModuleType("coinbase"), "coinbase.rest": rest}):
            with contextlib.redirect_stdout(output):
                self.assertEqual(self.module.test_coinbase_connection("input", "input"), (False, None))
                result = self.module.test_coinbase_accounts(client)
        self.assertEqual(result, {"status": "error", "error": "account_access_failed"})
        self.assertNotIn(marker, output.getvalue())


if __name__ == "__main__":
    unittest.main()
