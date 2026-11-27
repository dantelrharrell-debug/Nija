"""Rebuild offline strategy review and realized metrics from admitted evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory

from bot.kraken_shadow_outcomes import KrakenShadowOutcomes, _canonical, _evidence_digest
from bot.regime_performance_calibrator import RegimePerformanceCalibrator


def _realized_metrics(rows: list[dict]) -> dict:
    # An incomplete batch cannot support a total or a drawdown claim.
    if not rows or any(row["economics"] is None for row in rows):
        return {
            "status": "unavailable",
            "net_realized_pnl_usd": None,
            "execution_cost_usd": None,
            "realized_drawdown_usd": None,
            "profit_factor": None,
        }
    # Group simultaneous closes to avoid inventing a within-timestamp sequence.
    closes_by_time: dict[int, Decimal] = {}
    costs = wins = losses = Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 256
        for row in rows:
            amounts = row["economics"]
            execution_cost = Decimal(amounts["execution_cost_usd"])
            pnl = Decimal(amounts["gross_pnl_usd"]) - execution_cost
            stamp = amounts["closed_at_epoch"]
            closes_by_time[stamp] = closes_by_time.get(stamp, Decimal(0)) + pnl
            costs += execution_cost
            wins += max(pnl, Decimal(0))
            losses += max(-pnl, Decimal(0))
        cumulative = peak = drawdown = Decimal(0)
        for stamp in sorted(closes_by_time):
            cumulative += closes_by_time[stamp]
            peak = max(peak, cumulative)
            drawdown = max(drawdown, peak - cumulative)
        return {
            "status": "reconciled_sample",
            "net_realized_pnl_usd": _canonical(cumulative),
            "execution_cost_usd": _canonical(costs),
            "realized_drawdown_usd": _canonical(drawdown),
            "profit_factor": _canonical((wins / losses).quantize(Decimal("0.000001"))) if losses else None,
        }


def evaluate(inbox: KrakenShadowOutcomes, scope: str) -> dict:
    """Use only the latest 200 dated, cost-reconciled lots for shadow recommendations.

    An independent offline reader must have admitted each lot. Monetary metrics
    describe the inbox sample only and are withheld when any lot lacks amounts.
    """
    rows = inbox.evaluation_snapshot(scope)
    digest = _evidence_digest({"evaluation_schema": 1, "scope": scope, "rows": rows})
    dated = sorted(
        (row for row in rows if row["economics"] is not None),
        key=lambda row: (row["economics"]["closed_at_epoch"], row["lot_id"]),
    )
    training = dated[-200:]
    with TemporaryDirectory() as folder:
        engine = RegimePerformanceCalibrator(str(Path(folder) / "offline.json"), window=200)
        engine.selection_mode = "shadow"
        engine.selection_approved = False
        for row in training:
            amounts = row["economics"]
            notional = Decimal(amounts["opening_notional_usd"])
            stamp = datetime.fromtimestamp(amounts["closed_at_epoch"], tz=timezone.utc)
            engine.record_closed_trade(
                timestamp=stamp.isoformat(), symbol=row["symbol"], regime=row["regime"], strategy=row["strategy"],
                broker="kraken", net_return=float(Decimal(row["net_return"])),
                gross_return=float(Decimal(amounts["gross_pnl_usd"]) / notional),
                execution_cost_return=float(Decimal(amounts["execution_cost_usd"]) / notional),
            )
        return {
            "snapshot_sha256": digest,
            "sample_count": len(rows),
            "learning_sample_count": len(training),
            "metrics": _realized_metrics(rows),
            "recommendations": engine.report_all(),
            "owner_decisions": inbox.owner_decisions(scope, digest),
            "authorizes_orders": False,
        }
