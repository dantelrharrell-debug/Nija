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
                            data, calls tre_compute_position_size, applies
                            streak bonus + adaptive cooldown, and returns an
                            execution-ready position dict (or None to veto).

Integration flow (3️⃣)
----------------------
::

    from bot.risk.sizing import allocate_capital

    for symbol in trade_scanner.get_candidates():
        broker       = broker_selector.get_best_broker(symbol)
        balance      = broker_manager.get_balance(broker)
        streak       = performance_tracker.get_streak(symbol)
        last_trade   = trade_history.get_last_trade_ts(symbol)

        position = allocate_capital(
            account_balance = balance,
            symbol          = symbol,
            broker_name     = broker,
            analysis        = apex.analyze_market(symbol),
            broker          = broker_obj,
            streak          = streak,
            last_trade_ts   = last_trade,
        )
        if position:
            execution_engine.submit_order(position)
"""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Fee-aware minimum profit target ──────────────────────────────────────────
try:
    from bot.apex_config import get_min_profit_target as _get_min_profit_target
except ImportError:
    try:
        from apex_config import get_min_profit_target as _get_min_profit_target  # type: ignore[no-redef]
    except ImportError:
        def _get_min_profit_target() -> float:  # type: ignore[misc]
            return 0.0212  # 2.12% fallback

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
_DEFAULT_MAX_RISK_PCT:     float = 0.01   # 1 % of account per trade (Kelly ≤ 1%)
_DEFAULT_MAX_POSITION_PCT: float = 0.40   # 40 % hard cap (micro-platform floor)

# ── Micro-cap symbol hard cap (high-risk / low-liquidity assets) ──────────────
# Never allocate more than 35 % of balance to a single micro-cap symbol.
_MICRO_CAP_HARD_CAP_PCT:   float = 0.35

# ── MICRO_PLATFORM tier floor — small accounts must use ≥ 40 % per position ──
# Ensures positions are large enough to be fee-viable on STARTER/SAVER accounts.
MICRO_PLATFORM_MIN_POSITION_PCT: float = 0.40

# ── Execution friction fallback (fee + spread + slippage without buffer) ──────
# Used when per-symbol live rates are unavailable.
_FALLBACK_FRICTION_PCT: float = 0.0062  # 0.62 %

# ── Minimum net profit required at TP1 after friction deduction ──────────────
_MIN_NET_PROFIT_AT_TP1: float = 0.012   # 1.2 %

# ── Default TP tier percentages (aligned with apex_config.py TAKE_PROFIT) ────
_DEFAULT_TP1_PCT: float = 0.015   # 1.5 %
_DEFAULT_TP2_PCT: float = 0.025   # 2.5 %
_DEFAULT_TP3_PCT: float = 0.040   # 4.0 %

# ── Cooldown constants ────────────────────────────────────────────────────────
_COOLDOWN_BASE_SEC:  int = 60    # base cooldown when streak = 0
_COOLDOWN_MIN_SEC:   int = 30    # floor — never shorter than this
_COOLDOWN_MAX_SEC:   int = 120   # ceiling — never longer than this
_COOLDOWN_STEP_SEC:  int = 5     # seconds shaved off per consecutive win

# ── Streak bonus ──────────────────────────────────────────────────────────────
_STREAK_BONUS_PER_WIN: float = 0.002   # +0.2 % of size per consecutive win
_STREAK_BONUS_MAX:     float = 0.10    # cap bonus at +10 % of computed size


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

    Tries ``broker.get_current_price(symbol)`` first; returns None when
    the broker is unavailable or returns an invalid value.
    """
    if broker is not None:
        try:
            price = broker.get_current_price(symbol)
            if price and price > 0:
                return float(price)
        except Exception as exc:
            logger.debug("broker.get_current_price(%s) failed: %s", symbol, exc)
    return None


def _adaptive_cooldown(streak: int) -> int:
    """
    Return the cooldown period in seconds for the current *streak*.

    Higher streaks → shorter cooldown (bot is running hot; keep trading).
    Lower streaks  → longer cooldown  (slow down after cold or flat periods).

    Clamped to [_COOLDOWN_MIN_SEC, _COOLDOWN_MAX_SEC].
    """
    raw = _COOLDOWN_BASE_SEC - streak * _COOLDOWN_STEP_SEC
    return max(_COOLDOWN_MIN_SEC, min(_COOLDOWN_MAX_SEC, raw))


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
    streak: int = 0,
    last_trade_ts: Optional[float] = None,
    is_micro_cap: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    High-level capital allocator — execution-ready position dict or None.

    Extracts market parameters from *analysis*, applies streak compounding and
    adaptive cooldown, then returns a dict the Execution Engine can submit.

    Streak / cooldown logic
    -----------------------
    * **Streak bonus**: each consecutive win adds ``0.2 %`` to the computed
      size, capped at ``+10 %``.  Rewards the bot for staying disciplined on
      a hot streak without letting one lucky run blow the account.
    * **Adaptive cooldown**: base 60 s, reduced by 5 s per win (floor 30 s,
      ceiling 120 s).  A hot streak tightens the throttle; a cold or choppy
      market widens it automatically.
    * Both values are overridable via env vars
      ``NIJA_COOLDOWN_BASE_SEC`` / ``NIJA_COOLDOWN_STEP_SEC``.

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
        ``atr_pct``, ``stop_loss_pct``, ``profit_target_pct``, ``entry_price``,
        ``tp1_pct``, ``tp2_pct``, ``tp3_pct``.
    broker : object, optional
        Broker instance — used for live price lookup when *entry_price* is
        missing from *analysis*.
    streak : int
        Consecutive winning trades since last loss (0 = no streak / cold).
    last_trade_ts : float or None
        Unix timestamp of the last trade on *symbol* (``time.time()`` style).
        Pass ``None`` or ``0`` to skip the cooldown gate.
    is_micro_cap : bool
        When ``True`` applies the 35 % hard cap instead of the default 40 %.

    Returns
    -------
    dict or None
        Execution dict with keys ``symbol``, ``broker``, ``size_usd``,
        ``stop_loss_pct``, ``tp1_pct``, ``tp2_pct``, ``tp3_pct``,
        ``take_profit_pct`` (alias for tp1_pct), ``entry_price``,
        ``cooldown_sec``, ``streak``, ``post_only``.
        Returns ``None`` when the trade is vetoed (cooldown active, size ≤ 0,
        insufficient net profit at TP1, or hard cap exceeded).
    """
    _a = analysis or {}

    atr = float(_a.get("atr_pct",           0.02))
    sl  = float(_a.get("stop_loss_pct",      0.02))
    ep  = float(_a.get("entry_price",        0.0))

    # ── Resolve TP tier percentages ───────────────────────────────────────────
    # Prefer explicit tp1/tp2/tp3 from analysis; fall back to apex_config defaults.
    tp1_pct = float(_a.get("tp1_pct", _a.get("profit_target_pct", _DEFAULT_TP1_PCT)))
    tp2_pct = float(_a.get("tp2_pct", _DEFAULT_TP2_PCT))
    tp3_pct = float(_a.get("tp3_pct", _DEFAULT_TP3_PCT))

    # Ensure ordering and floor from apex_config minimum profit target
    _min_profit = _get_min_profit_target()
    tp1_pct = max(tp1_pct, _min_profit)
    tp2_pct = max(tp2_pct, tp1_pct * 1.5)
    tp3_pct = max(tp3_pct, tp2_pct * 1.5)

    # ── Net-profit veto — TP1 − friction < 1.2 % → reject ───────────────────
    # Ensures the bot never enters a trade whose first target cannot clear the
    # minimum post-friction profit margin.
    _friction = float(os.environ.get("NIJA_FRICTION_PCT", str(_FALLBACK_FRICTION_PCT)))
    _net_at_tp1 = tp1_pct - _friction
    if _net_at_tp1 < _MIN_NET_PROFIT_AT_TP1:
        logger.warning(
            "⚠️  allocate_capital: NET-PROFIT VETO for %s — "
            "TP1(%.2f%%) − friction(%.2f%%) = %.2f%% < required %.2f%%",
            symbol,
            tp1_pct * 100, _friction * 100, _net_at_tp1 * 100,
            _MIN_NET_PROFIT_AT_TP1 * 100,
        )
        return None

    # ── 1. Compute raw TRE size ───────────────────────────────────────────────
    size = tre_compute_position_size(
        account_balance  = account_balance,
        symbol           = symbol,
        broker_name      = broker_name,
        atr_pct          = atr,
        stop_loss_pct    = sl,
        take_profit_pct  = tp1_pct,
        entry_price      = ep,
        broker           = broker,
    )

    if size <= 0:
        logger.warning(
            "⚠️  allocate_capital: position vetoed for %s (below tier min / fee bleed)",
            symbol,
        )
        return None

    # ── 1b. ATR inverse scalar — reduce size when volatility is elevated ──────
    # ATR > 3 % → scale down; ATR < 1 % → scale up slightly (capped at 1.2×).
    if atr > 0:
        _atr_scalar = max(0.5, min(1.2, 0.02 / atr))
        if abs(_atr_scalar - 1.0) > 0.01:
            _pre_atr = size
            size = math.floor(size * _atr_scalar * 100) / 100
            logger.debug(
                "📐 ATR scalar %.2f× applied to %s: $%.2f → $%.2f (atr=%.1f%%)",
                _atr_scalar, symbol, _pre_atr, size, atr * 100,
            )

    # ── 2. Streak bonus — slight size increase on hot streaks ─────────────────
    # +0.2 % per consecutive win, capped at +10 % of the computed size.
    if streak > 0:
        bonus_pct = min(streak * _STREAK_BONUS_PER_WIN, _STREAK_BONUS_MAX)
        pre_bonus = size
        size = math.floor(size * (1.0 + bonus_pct) * 100) / 100
        logger.info(
            "🔥 Streak bonus ×%d applied to %s: $%.2f → $%.2f (+%.1f%%)",
            streak, symbol, pre_bonus, size, bonus_pct * 100,
        )

    # ── 3. Adaptive cooldown gate ─────────────────────────────────────────────
    # Dynamic window: base 60 s shrinks by 5 s per win (floor 30 s, cap 120 s).
    # Allows tighter cycling when the bot is on a confirmed hot streak.
    _base = int(os.environ.get("NIJA_COOLDOWN_BASE_SEC", str(_COOLDOWN_BASE_SEC)))
    _step = int(os.environ.get("NIJA_COOLDOWN_STEP_SEC", str(_COOLDOWN_STEP_SEC)))
    cooldown_sec = max(
        _COOLDOWN_MIN_SEC,
        min(_COOLDOWN_MAX_SEC, _base - streak * _step),
    )

    if last_trade_ts and last_trade_ts > 0:
        elapsed = time.time() - last_trade_ts
        if elapsed < cooldown_sec:
            remaining = cooldown_sec - elapsed
            logger.info(
                "⏱️  Cooldown active for %s — %ds remaining of %ds (streak=%d)",
                symbol, int(remaining), cooldown_sec, streak,
            )
            return None

    # ── 4. Hard cap — micro-cap 35 %, standard 40 % ───────────────────────────
    # Micro-cap assets carry higher liquidity risk; stricter ceiling applies.
    _hard_cap_pct = _MICRO_CAP_HARD_CAP_PCT if is_micro_cap else float(
        os.environ.get("NIJA_TRE_MAX_POSITION_PCT", str(_DEFAULT_MAX_POSITION_PCT))
    )
    cap = math.floor(account_balance * _hard_cap_pct * 100) / 100
    if size > cap:
        logger.debug(
            "allocate_capital: %s size capped $%.2f → $%.2f (%.0f%% of balance%s)",
            symbol, size, cap, _hard_cap_pct * 100,
            " — micro-cap" if is_micro_cap else "",
        )
        size = cap

    logger.info(
        "📊 Position size computed: $%.2f  [%s | streak=%d | cd=%ds | tp1=%.1f%% tp2=%.1f%% tp3=%.1f%%]",
        size, symbol, streak, cooldown_sec,
        tp1_pct * 100, tp2_pct * 100, tp3_pct * 100,
    )

    return {
        "symbol":          symbol,
        "broker":          broker_name,
        "size_usd":        size,
        "stop_loss_pct":   sl,
        # TP tiers as percentage fractions
        "tp1_pct":         tp1_pct,
        "tp2_pct":         tp2_pct,
        "tp3_pct":         tp3_pct,
        # Legacy alias consumed by parts of the system that use take_profit_pct
        "take_profit_pct": tp1_pct,
        "entry_price":     ep,
        "cooldown_sec":    cooldown_sec,
        "streak":          streak,
        "post_only":       True,
    }
