"""Read-only winner/loser reports from NIJA's existing confirmed-close ledger.

Reports keep broker and user ownership separate and read current fee-adjusted
values on every call. They never maintain a second P&L store, submit orders, or
change strategy weights/sizing. Borrow, funding and tax costs are not certified
by this ledger, so these figures are explicitly net of recorded execution fees.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any

LOGGER = logging.getLogger("nija.confirmed_performance")


def _metrics(values: list[float]) -> dict[str, Any]:
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gross_wins = sum(wins)
    gross_losses = -sum(losses)
    return {
        "trades": len(values), "wins": len(wins), "losses": len(losses),
        "breakeven": sum(v == 0 for v in values),
        "win_rate": len(wins) / len(values) if values else 0.0,
        "net_pnl_usd": sum(values),
        "expectancy_usd": sum(values) / len(values) if values else 0.0,
        "profit_factor": gross_wins / gross_losses if gross_losses else None,
        "profit_factor_status": "finite" if gross_losses else "no_losses" if wins else "no_profit",
        "sample_status": "descriptive_only" if len(values) >= 20 else "insufficient_sample",
    }


def get_confirmed_performance_report(
    ledger: Any, *, broker: str, user_id: str, limit: int = 1000,
) -> dict[str, Any]:
    """Summarize at most ``limit`` confirmed closes for one explicit owner.

    Broker identity comes from the exact broker field in the close transaction's
    ledger notes. Unscoped, manual, fee-inconsistent and ambiguous closes cannot
    enter this report. Unavailable strategy attribution remains unavailable.
    """
    broker = str(broker or "").strip().lower()
    user_id = str(user_id or "").strip()
    if not broker or not user_id or any(ch in broker for ch in ";%_ "):
        raise ValueError("explicit broker and user identity required")
    limit = max(1, min(int(limit), 10_000))
    with ledger._get_connection() as conn:
        # EXISTS avoids counting a position twice when duplicate recovery rows
        # are present. Requiring exactly one recorded broker prevents cross-venue
        # attribution of a reused position id. Account ownership is explicit.
        rows = conn.execute(
            """
            SELECT c.position_id, c.symbol, c.side, c.net_profit, c.gross_profit,
                   c.total_fees, c.entry_fee, c.exit_fee
            FROM completed_trades c
            WHERE c.user_id = ? AND c.exit_reason = 'canonical_confirmed_fill'
              AND EXISTS (
                  SELECT 1 FROM trade_ledger l
                  WHERE l.position_id = c.position_id AND l.user_id = c.user_id
                    AND l.action = 'CLOSE' AND COALESCE(l.order_id, '') != ''
                    AND l.notes LIKE ?
              )
              AND NOT EXISTS (
                  SELECT 1 FROM trade_ledger l
                  WHERE l.position_id = c.position_id AND l.user_id = c.user_id
                    AND l.action = 'CLOSE' AND COALESCE(l.notes, '') NOT LIKE ?
              )
            ORDER BY c.exit_time DESC, c.id DESC LIMIT ?
            """,
            (user_id, f"%; broker={broker}; %", f"%; broker={broker}; %", limit),
        ).fetchall()
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    values: list[float] = []
    excluded = 0
    for row in rows:
        try:
            net, gross, fees, entry_fee, exit_fee = map(float, row[3:8])
            if not all(math.isfinite(v) for v in (net, gross, fees, entry_fee, exit_fee)):
                raise ValueError("nonfinite P&L")
            if min(fees, entry_fee, exit_fee) < 0:
                raise ValueError("negative fees")
            if not math.isclose(fees, entry_fee + exit_fee, rel_tol=1e-8, abs_tol=1e-6):
                raise ValueError("fee mismatch")
            if not math.isclose(net, gross - fees, rel_tol=1e-8, abs_tol=1e-6):
                raise ValueError("net P&L mismatch")
            side = str(row[2] or "").strip().lower()
            if side in {"buy", "long"}:
                direction = "long"
            elif side in {"sell", "short"}:
                direction = "short"
            else:
                raise ValueError("unproven position direction")
            buckets[(str(row[1]), direction)].append(net)
            values.append(net)
        except (TypeError, ValueError):
            excluded += 1
    symbols = [{"symbol": symbol, "direction": direction, **_metrics(pnl)}
               for (symbol, direction), pnl in buckets.items()]
    return {
        "broker": broker, "user_id": user_id,
        "source": "canonical_confirmed_close_ledger",
        "cost_basis": "net_of_recorded_entry_and_exit_fees",
        "carry_costs_verified": False, "strategy_attribution": "unavailable",
        "window_limit": limit, "window_may_be_truncated": len(rows) == limit,
        "excluded_invalid_rows": excluded, "overall": _metrics(values),
        "winners": sorted((s for s in symbols if s["net_pnl_usd"] > 0),
                          key=lambda s: s["net_pnl_usd"], reverse=True),
        "losers": sorted((s for s in symbols if s["net_pnl_usd"] < 0),
                         key=lambda s: s["net_pnl_usd"]),
        "symbols": symbols, "automatic_trading_changes": False,
    }


def log_confirmed_performance(ledger: Any, *, broker: str, user_id: str) -> None:
    """Emit a scoped report; reporting failures never alter fill or exit truth."""
    try:
        report = get_confirmed_performance_report(ledger, broker=broker, user_id=user_id)
        overall = report["overall"]
        LOGGER.info(
            "CONFIRMED_PERFORMANCE broker=%s user_id=%s trades=%d wins=%d losses=%d "
            "breakeven=%d net_usd=%.8f expectancy_usd=%.8f profit_factor=%s "
            "winners=%s losers=%s source=canonical_close_ledger carry_costs_verified=false",
            broker, user_id, overall["trades"], overall["wins"], overall["losses"],
            overall["breakeven"], overall["net_pnl_usd"], overall["expectancy_usd"],
            overall["profit_factor"],
            [s["symbol"] for s in report["winners"][:3]],
            [s["symbol"] for s in report["losers"][:3]],
        )
    except Exception as exc:
        LOGGER.warning("CONFIRMED_PERFORMANCE_UNAVAILABLE error=%s", type(exc).__name__)
