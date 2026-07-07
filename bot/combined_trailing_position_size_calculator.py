"""Position-size calculator for combined trailing protection.

Computes a safe notional and quantity before entry using:
- account equity/cash
- risk budget percentage
- entry price
- combined trailing stop-loss distance
- min/max notional clamps

This module is calculation-only. It does not force an order. Runtime patches can
call ``calculate_combined_trailing_position_size`` before compiling/submitting a
new entry.
"""
from __future__ import annotations

import logging, os
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger("nija.combined_trailing_size")


def _f(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return d if x != x else x
    except Exception:
        return d


def _pct_env(name: str, default: float, floor: float, ceiling: float) -> float:
    return max(floor, min(_f(os.environ.get(name), default), ceiling))


def _money_env(name: str, default: float, floor: float = 0.0) -> float:
    return max(floor, _f(os.environ.get(name), default))


@dataclass
class CombinedTrailingPositionSize:
    symbol: str
    side: str
    entry_price: float
    equity_usd: float
    risk_pct: float
    risk_budget_usd: float
    stop_distance_pct: float
    stop_price: float
    raw_notional_usd: float
    max_notional_usd: float
    min_notional_usd: float
    final_notional_usd: float
    quantity: float
    clamped_by_cash: bool
    clamped_by_max_notional: bool
    lifted_to_min_notional: bool
    valid: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_combined_trailing_position_size(
    *,
    symbol: str,
    side: str = "buy",
    entry_price: float,
    equity_usd: float,
    available_cash_usd: float | None = None,
    min_notional_usd: float | None = None,
    max_notional_usd: float | None = None,
    risk_pct: float | None = None,
    stop_distance_pct: float | None = None,
) -> dict[str, Any]:
    """Return a position-size plan for combined trailing protection.

    Formula:
        risk_budget = equity * risk_pct
        raw_notional = risk_budget / stop_distance_pct
        quantity = final_notional / entry_price
    """
    symbol = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    side = str(side or "buy").strip().lower()
    entry = _f(entry_price)
    equity = max(0.0, _f(equity_usd))
    cash = equity if available_cash_usd is None else max(0.0, _f(available_cash_usd))
    risk = risk_pct if risk_pct is not None else _pct_env("NIJA_COMBINED_SIZE_RISK_PCT", 0.005, 0.0005, 0.05)
    risk = max(0.0001, min(_f(risk), 0.10))
    stop_dist = stop_distance_pct if stop_distance_pct is not None else _pct_env("NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT", 0.006, 0.001, 0.25)
    stop_dist = max(0.0005, min(_f(stop_dist), 0.50))
    min_notional = min_notional_usd if min_notional_usd is not None else _money_env("NIJA_COMBINED_SIZE_MIN_NOTIONAL_USD", _money_env("MIN_TRADE_USD", 10.0))
    max_notional_cfg = max_notional_usd if max_notional_usd is not None else _money_env("NIJA_COMBINED_SIZE_MAX_NOTIONAL_USD", cash)
    max_notional = max(0.0, min(_f(max_notional_cfg), cash))

    if not symbol:
        reason = "missing_symbol"
        valid = False
    elif entry <= 0:
        reason = "invalid_entry_price"
        valid = False
    elif equity <= 0 or cash <= 0:
        reason = "no_equity_or_cash"
        valid = False
    elif max_notional <= 0:
        reason = "max_notional_zero"
        valid = False
    else:
        reason = "ok"
        valid = True

    risk_budget = equity * risk
    raw_notional = risk_budget / stop_dist if stop_dist > 0 else 0.0
    clamped_cash = raw_notional > cash
    clamped_max = raw_notional > max_notional
    final_notional = min(raw_notional, cash, max_notional)
    lifted = False
    if valid and min_notional > 0 and 0 < final_notional < min_notional <= max_notional:
        final_notional = min_notional
        lifted = True
    if valid and final_notional < min_notional:
        valid = False
        reason = "below_min_notional_after_clamps"
    qty = final_notional / entry if valid and entry > 0 else 0.0
    if side in {"long", "buy"}:
        stop_price = entry * (1.0 - stop_dist)
    else:
        stop_price = entry * (1.0 + stop_dist)

    result = CombinedTrailingPositionSize(
        symbol=symbol,
        side=side,
        entry_price=entry,
        equity_usd=equity,
        risk_pct=risk,
        risk_budget_usd=risk_budget,
        stop_distance_pct=stop_dist,
        stop_price=stop_price,
        raw_notional_usd=raw_notional,
        max_notional_usd=max_notional,
        min_notional_usd=_f(min_notional),
        final_notional_usd=final_notional if valid else 0.0,
        quantity=qty,
        clamped_by_cash=clamped_cash,
        clamped_by_max_notional=clamped_max,
        lifted_to_min_notional=lifted,
        valid=valid,
        reason=reason,
    ).to_dict()
    logger.info(
        "COMBINED_TRAILING_SIZE_CALCULATED symbol=%s side=%s entry=%.8f equity=%.2f risk_pct=%.4f stop_dist=%.4f notional=%.2f qty=%.8f valid=%s reason=%s",
        symbol, side, entry, equity, risk, stop_dist, result["final_notional_usd"], qty, valid, reason,
    )
    return result


def install_import_hook() -> None:
    logger.warning("COMBINED_TRAILING_SIZE_CALCULATOR_READY")


__all__ = ["calculate_combined_trailing_position_size", "CombinedTrailingPositionSize", "install_import_hook"]
