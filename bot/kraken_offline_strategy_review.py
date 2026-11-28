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


def _observed_cost_by_regime(rows: list[dict]) -> list[dict]:
    # The existing admission contract proves the amounts, not an ex-ante
    # benchmark price or an independent reconstruction of market regimes.
    totals: dict[str, dict] = {}
    with localcontext() as ctx:
        ctx.prec = 256
        for row in rows:
            amounts = row["economics"]
            gross = Decimal(amounts["gross_pnl_usd"])
            cost = Decimal(amounts["execution_cost_usd"])
            entry = totals.setdefault(row["regime"], {
                "gross_realized_pnl_usd": Decimal(0),
                "recorded_execution_cost_usd": Decimal(0),
                "net_realized_pnl_usd": Decimal(0),
                "sample_count": 0,
                "gross_winner_lots_erased_by_cost": 0,
            })
            entry["gross_realized_pnl_usd"] += gross
            entry["recorded_execution_cost_usd"] += cost
            entry["net_realized_pnl_usd"] += gross - cost
            entry["sample_count"] += 1
            entry["gross_winner_lots_erased_by_cost"] += int(gross > 0 and gross - cost <= 0)
    return [
        {"admitted_regime_label": label, **{
            field: _canonical(value) if isinstance(value, Decimal) else value
            for field, value in totals[label].items()
        }}
        for label in sorted(totals)
    ]


def evaluate(
    inbox: KrakenShadowOutcomes, scope: str, *, training_through_epoch: int | None = None,
) -> dict:
    """Build an isolated report; an explicit cutoff prevents future outcomes entering training.

    The default report flags its recommendations as in-sample. A chronological
    review fits on at most 200 eligible lots through the supplied cutoff,
    measures only realized historical outcomes afterward, and never interprets
    them as counterfactual returns from either the candidate or baseline.
    """
    if training_through_epoch is not None and (
        type(training_through_epoch) is not int or not 0 < training_through_epoch < 253402300800
    ):
        raise ValueError("invalid offline training cutoff")
    rows = inbox.evaluation_snapshot(scope)
    evidence = {"evaluation_schema": 1, "scope": scope, "rows": rows}
    dated = sorted(
        (row for row in rows if row["economics"] is not None),
        key=lambda row: (row["economics"]["closed_at_epoch"], row["lot_id"]),
    )
    chronology = {
        "status": "cutoff_not_set",
        "training_through_epoch": training_through_epoch,
        "holdout_sample_count": 0,
        "lots_without_economics": len(rows) - len(dated),
        "observed_holdout_metrics": None,
        "observed_holdout_cost_by_regime": None,
        "slippage_status": "unavailable_no_benchmark_evidence",
        "candidate_comparison_status": "not_evaluated",
        "candidate_comparison": None,
    }
    if training_through_epoch is None:
        training = dated[-200:]
        recommendation_basis = "in_sample_shadow_only"
    else:
        evidence.update(evaluation_schema=3, training_through_epoch=training_through_epoch)
        training = [
            row for row in dated if row["economics"]["closed_at_epoch"] <= training_through_epoch
        ][-200:]
        holdout = [
            row for row in dated if row["economics"]["closed_at_epoch"] > training_through_epoch
        ]
        chronology.update(
            status="separate_samples" if training and holdout else "insufficient_dated_samples",
            holdout_sample_count=len(holdout),
            observed_holdout_metrics=_realized_metrics(holdout) if holdout else None,
            observed_holdout_cost_by_regime=_observed_cost_by_regime(holdout) if holdout else None,
        )
        recommendation_basis = "training_samples_only"
    digest = _evidence_digest(evidence)
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
            "recommendation_basis": recommendation_basis,
            "chronological_review": chronology,
            "owner_decisions": inbox.owner_decisions(scope, digest),
            "authorizes_orders": False,
        }
