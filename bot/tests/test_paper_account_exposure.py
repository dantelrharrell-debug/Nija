"""Paper-only exposure caps and accounting regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.paper_trading import PaperTradingAccount


class PaperExposureTests(unittest.TestCase):
    """Exercise cash, gross exposure, symbol cap, and short-sale equity."""

    def make_account(self, directory: str) -> PaperTradingAccount:
        """Create a fresh paper account with an isolated state file."""
        with patch.object(PaperTradingAccount, "_load_state"):
            account = PaperTradingAccount(initial_balance=1000.0)
        account.data_file = str(Path(directory) / "paper.json")
        return account

    def test_caps_use_actual_paper_equity_and_block_unsafe_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            account = self.make_account(directory)
            first = account.open_position("BTC-USD", 2, 100, 90)
            self.assertIsNotNone(first)
            self.assertEqual(account.get_equity(), 1000)
            account.update_position(first, 110)
            self.assertEqual(account.get_equity(), 1020)
            self.assertIsNone(account.open_position("BTC-USD", 1, 100, 90))
            second = account.open_position("ETH-USD", 2.5, 100, 90)
            self.assertIsNotNone(second)
            self.assertIsNone(account.open_position("SOL-USD", 1.5, 100, 90))
            self.assertEqual(len(account.positions), 2)
            self.assertEqual(len(account.trades), 2)
            self.assertEqual(account.close_position(first, -10), 0.0)
            self.assertEqual(account.get_equity(), 1020)

    def test_short_returns_reserved_principal_and_gain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            account = self.make_account(directory)
            short = account.open_position("BTC-USD", 2, 100, 110, side="short")
            self.assertIsNotNone(short)
            account.update_position(short, 90)
            self.assertEqual(account.get_equity(), 1020)
            self.assertEqual(account.close_position(short, 90), 20)
            self.assertEqual(account.balance, 1020)
            self.assertEqual(account.get_equity(), 1020)


if __name__ == "__main__":
    unittest.main()
