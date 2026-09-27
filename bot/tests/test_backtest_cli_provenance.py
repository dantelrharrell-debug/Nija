"""The CLI must not present its SMA illustration as an APEX backtest."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bot.tests.test_paper_break_retest_replay import _break_retest_bars


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "nija_execution_cli.py"


class BacktestCliProvenanceTests(unittest.TestCase):
    """Check a rejected APEX request and the explicit demo export label."""

    def test_apex_request_is_rejected_before_loading_data(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "backtest", "--strategy", "apex_v71",
             "--symbol", "BTC-USD", "--data", "missing.csv"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)
        self.assertNotIn("Starting backtest", result.stderr)

    def test_demo_export_identifies_illustrative_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bars = Path(directory) / "bars.csv"
            out = Path(directory) / "backtest.json"
            rows = ["timestamp,open,high,low,close,volume"]
            for index in range(45):
                close = 100 + index * 0.01
                rows.append(f"2026-01-01T{index // 60:02d}:{index % 60:02d}:00,{close},{close+1},{close-1},{close},100")
            bars.write_text("\n".join(rows) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CLI), "backtest", "--strategy", "sma_demo",
                 "--symbol", "BTC-USD", "--data", str(bars), "--output", str(out)],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(out.read_text(encoding="utf-8"), parse_constant=lambda x: self.fail(x))
            self.assertEqual(data["analysis"]["kind"], "demonstration_only")
            self.assertEqual(data["analysis"]["strategy"], "sma_demo")
            self.assertFalse(data["analysis"]["live_readiness_granted"])
            self.assertTrue(any("does not run NIJA APEX" in line for line in data["analysis"]["limitations"]))

    def test_replay_export_is_strict_json_and_cannot_be_compared_as_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bars = Path(directory) / "bars.csv"
            out = Path(directory) / "replay.json"
            live = Path(directory) / "live"
            live.mkdir()
            (live / "tracker_state.json").write_text('{"trades": []}', encoding="utf-8")
            _break_retest_bars().rename_axis("timestamp").to_csv(bars)
            run = subprocess.run(
                [sys.executable, str(CLI), "backtest", "--strategy", "break_retest_replay",
                 "--symbol", "BTC-USD", "--data", str(bars), "--output", str(out)],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads(out.read_text(encoding="utf-8"), parse_constant=lambda x: self.fail(x))
            self.assertEqual(data["analysis"]["kind"], "detector_replay_only")
            self.assertEqual(data["summary"]["total_trades"], 1)
            compare = subprocess.run(
                [sys.executable, str(CLI), "compare", "--backtest", str(out), "--live", str(live)],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(compare.returncode, 0)
            self.assertIn("Cannot compare", compare.stderr)


if __name__ == "__main__":
    unittest.main()
