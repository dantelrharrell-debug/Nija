"""Read-only review of NIJA's recorded paper trades.

This module never calls a broker, selects a strategy, or grants live readiness.
The legacy paper account stores P&L without fees, slippage, or a price history;
the report makes those limits explicit instead of presenting a profitability
claim from incomplete evidence.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def review_paper_account(
    state: Mapping[str, Any], *, recent_limit: int = 20, stress_drop_pct: float = 0.20
) -> dict[str, Any]:
    """Summarize closed paper fills and estimate a simple open-position shock.

    A close row is a *fill*, not necessarily a completed trade: partial closes
    remain separate.  The stress scenario assumes every marked asset falls by
    the same percentage, with no fees, slippage, or liquidity effects.
    """
    if recent_limit < 1 or not 0 < stress_drop_pct < 1:
        raise ValueError("recent_limit must be positive and stress_drop_pct between 0 and 1")
    rows = state.get("trades")
    positions = state.get("positions")
    if not isinstance(rows, list) or not isinstance(positions, dict):
        raise ValueError("paper state must contain a trades list and positions object")

    closes: list[dict[str, Any]] = []
    malformed_closes = 0
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("action", "")).startswith("CLOSE"):
            continue
        pnl = _finite_number(row.get("pnl"))
        if pnl is None or not str(row.get("symbol", "")).strip():
            malformed_closes += 1
            continue
        closes.append({
            "position_id": str(row.get("position_id", "")),
            "timestamp": str(row.get("timestamp", "")),
            "symbol": str(row["symbol"]),
            "action": str(row["action"]),
            "reason": str(row.get("reason", "")),
            "recorded_pnl_usd": pnl,
        })

    wins = [row["recorded_pnl_usd"] for row in closes if row["recorded_pnl_usd"] > 0]
    losses = [row["recorded_pnl_usd"] for row in closes if row["recorded_pnl_usd"] < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    by_symbol: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"closed_fills": 0, "recorded_pnl_usd": 0.0}
    )
    for row in closes:
        symbol_summary = by_symbol[row["symbol"]]
        symbol_summary["closed_fills"] += 1
        symbol_summary["recorded_pnl_usd"] += row["recorded_pnl_usd"]

    exposure = 0.0
    shock_pnl = 0.0
    invalid_positions = 0
    for position in positions.values():
        if not isinstance(position, dict):
            invalid_positions += 1
            continue
        size = _finite_number(position.get("size"))
        price = _finite_number(position.get("current_price"))
        side = position.get("side")
        if size is None or price is None or size <= 0 or price <= 0 or side not in ("long", "short"):
            invalid_positions += 1
            continue
        marked_notional = size * price
        exposure += marked_notional
        shock_pnl += (-1 if side == "long" else 1) * marked_notional * stress_drop_pct

    warnings: list[str] = []
    if len(closes) < 20:
        warnings.append("Fewer than 20 closed fills; pattern claims are premature.")
    if malformed_closes or invalid_positions:
        warnings.append("Malformed records were excluded; check the source journal.")
    if closes and not all("fees" in row or "net_pnl" in row for row in rows if isinstance(row, dict)
                          and str(row.get("action", "")).startswith("CLOSE")):
        warnings.append("Recorded paper P&L does not establish results after fees and slippage.")
    if closes and not any(isinstance(row, dict) and row.get("strategy") for row in rows):
        warnings.append("Strategy IDs are absent; results cannot be attributed to a strategy.")
    warnings.append("A uniform price shock is a scenario, not a forecast or a hedge recommendation.")

    recorded_total = _finite_number(state.get("total_pnl"))
    summed_total = sum(row["recorded_pnl_usd"] for row in closes)
    if recorded_total is not None and abs(recorded_total - summed_total) > 0.01:
        warnings.append("Account total P&L disagrees with valid closed-fill records.")

    return {
        "mode": "paper_read_only",
        "closed_fills": len(closes),
        "malformed_closes": malformed_closes,
        "winning_fills": len(wins),
        "losing_fills": len(losses),
        "win_rate_pct": 100 * len(wins) / len(closes) if closes else None,
        "recorded_pnl_usd": summed_total,
        "gross_profit_usd": gross_profit,
        "gross_loss_usd": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "by_symbol": dict(sorted(by_symbol.items())),
        "recent_closed_fills": closes[-recent_limit:],
        "open_position_shock": {
            "market_drop_pct": 100 * stress_drop_pct,
            "marked_notional_usd": exposure,
            "estimated_pnl_change_usd": shock_pnl,
            "invalid_positions": invalid_positions,
        },
        "live_readiness_granted": False,
        "warnings": warnings,
    }
