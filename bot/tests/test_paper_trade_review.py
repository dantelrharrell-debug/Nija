"""Evidence and isolation checks for the read-only paper review."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.paper_trade_review import review_paper_account


REPO_ROOT = Path(__file__).resolve().parents[2]


class PaperTradeReviewTests(unittest.TestCase):
    """Exercise actual PaperTradingAccount state shapes and CLI behavior."""

    def test_partial_fills_and_open_shock_are_labeled_without_live_authority(self) -> None:
        state = {
            "total_pnl": 9.0,
            "trades": [
                {"position_id": "BTC-1", "action": "OPEN", "symbol": "BTC-USD", "price": 100},
                {"position_id": "BTC-1", "action": "CLOSE_50.0%", "symbol": "BTC-USD",
                 "pnl": 12.0, "reason": "PARTIAL_PROFIT", "timestamp": "2026-01-02T00:00:00"},
                {"position_id": "ETH-1", "action": "CLOSE_100.0%", "symbol": "ETH-USD",
                 "pnl": -3.0, "reason": "STOP_LOSS", "timestamp": "2026-01-03T00:00:00"},
            ],
            "positions": {
                "BTC-1": {"side": "long", "size": 10, "current_price": 100},
                "ETH-2": {"side": "short", "size": 5, "current_price": 100},
            },
        }
        report = review_paper_account(state)
        self.assertEqual(report["closed_fills"], 2)
        self.assertEqual(report["recorded_pnl_usd"], 9.0)
        self.assertEqual(report["profit_factor"], 4.0)
        self.assertEqual(report["win_rate_pct"], 50.0)
        self.assertEqual(report["open_position_shock"]["estimated_pnl_change_usd"], -100.0)
        self.assertFalse(report["live_readiness_granted"])
        self.assertTrue(any("fees and slippage" in warning for warning in report["warnings"]))

    def test_bad_records_and_disagreement_are_visible(self) -> None:
        report = review_paper_account({
            "trades": [{"action": "CLOSE_100.0%", "symbol": "BTC-USD", "pnl": "NaN"}],
            "positions": {"x": {"side": "long", "size": -1, "current_price": 100}},
            "total_pnl": 17,
        })
        self.assertEqual(report["closed_fills"], 0)
        self.assertEqual(report["malformed_closes"], 1)
        self.assertEqual(report["open_position_shock"]["invalid_positions"], 1)
        self.assertIsNone(report["profit_factor"])
        self.assertTrue(any("disagrees" in warning for warning in report["warnings"]))
        self.assertNotIn("NaN", json.dumps(report, allow_nan=False))

    def test_cli_reads_without_mutating_paper_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper_trading_data.json"
            original = '{"trades": [], "positions": {}, "balance": 1000}'
            source.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "scripts.review_paper_trades", "--input", str(source)],
                cwd=REPO_ROOT, capture_output=True, text=True, check=True,
            )
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertEqual(json.loads(result.stdout)["mode"], "paper_read_only")
            self.assertNotIn("BOT_PACKAGE_STARTUP", result.stderr)


if __name__ == "__main__":
    unittest.main()
