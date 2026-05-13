import os
import unittest
from unittest.mock import patch

from bot.startup_env import resolve_coinbase_retail_portfolio_id


class TestStartupEnv(unittest.TestCase):
    def test_resolve_coinbase_retail_portfolio_id_returns_none_for_whitespace(self):
        with patch.dict(os.environ, {"COINBASE_RETAIL_PORTFOLIO_ID": "   \n\t  "}):
            self.assertIsNone(resolve_coinbase_retail_portfolio_id())

    def test_resolve_coinbase_retail_portfolio_id_returns_trimmed_value(self):
        with patch.dict(os.environ, {"COINBASE_RETAIL_PORTFOLIO_ID": "  portfolio-123  "}):
            self.assertEqual(resolve_coinbase_retail_portfolio_id(), "portfolio-123")

    def test_resolve_coinbase_retail_portfolio_id_filters_non_printable_chars(self):
        with patch.dict(os.environ, {"COINBASE_RETAIL_PORTFOLIO_ID": "\u200bportfolio-123\u200b"}):
            self.assertEqual(resolve_coinbase_retail_portfolio_id(), "portfolio-123")


if __name__ == "__main__":
    unittest.main()
