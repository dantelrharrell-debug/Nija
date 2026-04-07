"""
bot.risk.sizing — TRE-aware position sizing
============================================

This module is the **single import point** for position-size decisions.

Public symbols
--------------
calculate_position_size   : fee-aware, 10-step sizer (from position_sizer.py)
tre_compute_position_size : Tiered Risk Engine (TRE) wrapper — enforces broker
                            minimums, per-symbol win-rate, and risk caps before
                            delegating to calculate_position_size.
allocate_capital          : high-level capital allocator — fetches live market
                            data, calls tre_compute_position_size, and returns
                            an execution-ready position dict (or None to veto).

Usage
-----
::

    from bot.risk.sizing import calculate_position_size, allocate_capital

    # Low-level (use when you already have all parameters):
    size = calculate_position_size(
        account_balance=balance,
        entry_price=price,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        atr_pct=atr,
    )

    # High-level (use inside the scan / execution loop):
    position = allocate_capital(
        account_balance=balance,
        symbol=symbol,
        broker_name=broker,
        analysis=analysis_dict,   # from apex.analyze_market()
        broker=broker_obj,        # optional – broker instance for live price
    )
    if position is None:
        continue   # trade vetoed
    execution_engine.submit(position)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Re-export base sizer so callers only need one import ──────────────────────
try:
    from position_sizer import calculate_position_size
except ImportError:
    try:
        from bot.position_sizer import calculate_position_size
    except ImportError:
        def calculate_position_size(*args, **kwargs) -> float:  # type: ignore[misc]
            logger.error("calculate_position_size unavailable — position_sizer not found")
            return 0.0

# ── Broker minimums (mirrors BROKER_MIN_ORDER_USD in nija_apex_strategy_v71) ──
_BROKER_MIN_USD: Dict[str, float] = {
    "kraken":   10.5,
    "coinbase":  5.0,
    "binance":  10.0,
    "okx":       5.0,
    "alpaca":    1.0,
}
_DEFAULT_BROKER_MIN_USD: float = 10.0

# ── Default TRE risk parameters ───────────────────────────────────────────────
_DEFAULT_MAX_RISK_PCT:     float = 0.01   # 1 % of account per trade
_DEFAULT_MAX_POSITION_PCT: float = 0.40   # 40 % hard cap (Fix 4)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_tier_min_trade(broker: str) -> float:
    """Return the minimum tradeable USD amount for *broker*."""
    return _BROKER_MIN_USD.get(broker.lower(), _DEFAULT_BROKER_MIN_USD)


def _get_symbol_win_rate(symbol: str, default: float = 0.55) -> float:
    """
    Query the live SymbolPerformanceTracker for *symbol*'s historical win rate.
    Falls back to *default* when the tracker is unavailable or has no data.
    """
    try:
        from symbol_performance_tracker import get_symbol_performance_tracker
        tracker = get_symbol_performance_tracker()
        stats = tracker.get_symbol_stats(symbol)
        if stats is not None and stats.trade_count >= 3:
            return float(stats.win_rate)
    except Exception as exc:
        logger.debug("SymbolPerformanceTracker unavailable for %s: %s", symbol, exc)
    return default


def _get_live_price(symbol: str, broker: Any = None) -> Optional[float]:
    """
    Return the current mid-price for *symbol*.

    Tries, in order:
      1. ``broker.get_current_price(symbol)`` (fastest — already in memory)
      2. NIJAApexStrategyV71._get_current_price stub (fallback)
    """
    if broker is not None:
        try:
            price = broker.get_current_price(symbol)
            if price and price > 0:
                return float(price)
        except Exception as exc:
            logger.debug("broker.get_current_price(%s) failed: %s", symbol, exc)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 2️⃣  TRE Wrapper
# ─────────────────────────────────────────────────────────────────────────────

def tre_compute_position_size(
    account_balance: float,
    symbol: str,
    broker_name: str,
    atr_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    entry_price: Optional[float] = None,
    win_rate: Optional[float] = None,
    broker: Any = None,
) -> float:
    """
    TRE-aware position size calculation.

    Fetches Tiered Risk Engine constraints (broker minimum, max-risk, max
    position), resolves live win-rate from the SymbolPerformanceTracker, then
    delegates to :func:`calculate_position_size`.

    Returns
    -------
    float
        Position size in USD, or 0.0 when the trade is vetoed (below tier
        minimum or net profit too low after execution friction).
    """
    # ── Tier constraints ──────────────────────────────────────────────────────
    tier_min     = _get_tier_min_trade(broker_name)
    max_risk     = float(os.environ.get("NIJA_TRE_MAX_RISK_PCT",     str(_DEFAULT_MAX_RISK_PCT)))
    max_position = float(os.environ.get("NIJA_TRE_MAX_POSITION_PCT", str(_DEFAULT_MAX_POSITION_PCT)))

    # ── Resolve entry price ───────────────────────────────────────────────────
    price = entry_price
    if not price or price <= 0:
        price = _get_live_price(symbol, broker) or 0.0

    # ── Resolve win rate ──────────────────────────────────────────────────────
    if win_rate is None or win_rate <= 0:
        win_rate = _get_symbol_win_rate(symbol)

    # ── Compute raw size ──────────────────────────────────────────────────────
    size = calculate_position_size(
        account_balance  = account_balance,
        entry_price      = price,
        stop_loss_pct    = stop_loss_pct,
        take_profit_pct  = take_profit_pct,
        atr_pct          = atr_pct,
        win_rate         = win_rate,
        broker           = broker_name,
        max_risk_pct     = max_risk,
        max_position_pct = max_position,
    )

    # ── Enforce tier minimum ──────────────────────────────────────────────────
    if size < tier_min:
        logger.info(
            "tre_compute_position_size: %s VETOED — computed size $%.2f < tier min $%.2f (%s)",
            symbol, size, tier_min, broker_name,
        )
        return 0.0

    logger.info(
        "📊 TRE position size: %s $%.2f  (balance=$%.2f sl=%.1f%% tp=%.1f%% atr=%.1f%% wr=%.0f%%)",
        symbol, size,
        account_balance, stop_loss_pct * 100, take_profit_pct * 100,
        atr_pct * 100, win_rate * 100,
    )
    return size


# ─────────────────────────────────────────────────────────────────────────────
# 3️⃣  CapitalAllocator
# ─────────────────────────────────────────────────────────────────────────────

def allocate_capital(
    account_balance: float,
    symbol: str,
    broker_name: str,
    analysis: Optional[Dict[str, Any]] = None,
    broker: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    High-level capital allocator — execution-ready position dict or None.

    Extracts market parameters from *analysis* (the dict returned by
    ``apex.analyze_market()``), calls :func:`tre_compute_position_size`,
    and returns a dict that the Execution Engine can submit directly.

    Parameters
    ----------
    account_balance : float
        Current free balance in USD.
    symbol : str
        Trading pair, e.g. ``"XBT/USD"`` or ``"BTC-USD"``.
    broker_name : str
        Lowercase broker identifier, e.g. ``"kraken"`` or ``"coinbase"``.
    analysis : dict, optional
        Output of ``apex.analyze_market()``.  Keys used:
        ``atr_pct``, ``stop_loss_pct``, ``profit_target_pct``, ``entry_price``.
    broker : object, optional
        Broker instance — used for live price lookup when *entry_price* is
        missing from *analysis*.

    Returns
    -------
    dict or None
        Execution dict with keys ``symbol``, ``broker``, ``size_usd``,
        ``stop_loss_pct``, ``take_profit_pct``, ``entry_price``.
        Returns ``None`` when the trade is vetoed (size ≤ 0).
    """
    _a = analysis or {}

    atr = float(_a.get("atr_pct",           0.02))
    sl  = float(_a.get("stop_loss_pct",      0.02))
    tp  = float(_a.get("profit_target_pct",  0.035))
    ep  = float(_a.get("entry_price",        0.0))

    size = tre_compute_position_size(
        account_balance  = account_balance,
        symbol           = symbol,
        broker_name      = broker_name,
        atr_pct          = atr,
        stop_loss_pct    = sl,
        take_profit_pct  = tp,
        entry_price      = ep,
        broker           = broker,
    )

    if size <= 0:
        logger.warning(
            "⚠️  allocate_capital: position vetoed for %s (below tier min / fee bleed)",
            symbol,
        )
        return None

    return {
        "symbol":          symbol,
        "broker":          broker_name,
        "size_usd":        size,
        "stop_loss_pct":   sl,
        "take_profit_pct": tp,
        "entry_price":     ep,
    }
