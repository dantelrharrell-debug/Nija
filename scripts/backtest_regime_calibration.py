"""Walk-forward evaluation of NIJA regime calibration against trade outcomes."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.regime_performance_calibrator import RegimePerformanceCalibrator


def load_attribution_trades(path: Path) -> List[Dict[str, object]]:
    """Load chronologically ordered closed outcomes from an attribution JSONL file."""
    trades: List[Dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("status") != "closed":
            continue
        trades.append(row)
    return sorted(trades, key=lambda row: str(row.get("closed_at") or row.get("timestamp") or ""))


def max_drawdown(returns: Iterable[float]) -> float:
    """Calculate compounded peak-to-trough drawdown."""
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in returns:
        equity *= max(0.0, 1.0 + value)
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    return drawdown


def evaluate_walk_forward(trades: List[Dict[str, object]]) -> Dict[str, object]:
    """Compare baseline and downside-only calibrated returns without lookahead."""
    baseline: List[float] = []
    calibrated: List[float] = []
    active_trades = 0
    with tempfile.TemporaryDirectory() as temp_dir:
        calibrator = RegimePerformanceCalibrator(str(Path(temp_dir) / "state.json"))
        for trade in trades:
            regime = trade.get("regime_family") or trade.get("regime") or "default"
            strategy = str(trade.get("strategy") or "APEX_V71")
            controls = calibrator.get_control_preview(regime, strategy)
            trade_return = float(trade.get("pnl") or 0.0)
            size_multiplier = float(controls["position_size_multiplier"])
            baseline.append(trade_return)
            calibrated.append(trade_return * size_multiplier)
            active_trades += int(bool(controls["eligible"]))
            calibrator.record_closed_trade(
                symbol=trade.get("symbol") or "unknown",
                regime=regime,
                strategy=strategy,
                broker=trade.get("broker") or "unknown",
                side=trade.get("side") or "unknown",
                net_return=trade_return,
                gross_return=trade_return,
                execution_cost_return=0.0,
                mfe_return=0.0,
                mae_return=min(0.0, trade_return),
                exit_reason=trade.get("exit_reason") or "historical",
                confidence=trade.get("confidence"),
            )
    return {
        "trades": len(trades),
        "calibration_active_trades": active_trades,
        "baseline_total_return": round(sum(baseline), 8),
        "calibrated_total_return": round(sum(calibrated), 8),
        "baseline_max_drawdown": round(max_drawdown(baseline), 8),
        "calibrated_max_drawdown": round(max_drawdown(calibrated), 8),
        "passes_non_degradation": (
            sum(calibrated) >= sum(baseline)
            and max_drawdown(calibrated) <= max_drawdown(baseline)
            and active_trades > 0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Trade attribution JSONL path")
    args = parser.parse_args()
    trades = load_attribution_trades(args.path)
    report = evaluate_walk_forward(trades)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passes_non_degradation"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
