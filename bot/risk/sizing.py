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

# ── Cooldown constants ────────────────────────────────────────────────────────
_COOLDOWN_BASE_SEC:  int = 60    # base cooldown when streak = 0
_COOLDOWN_MIN_SEC:   int = 30    # floor — never shorter than this
_COOLDOWN_MAX_SEC:   int = 120   # ceiling — never longer than this
_COOLDOWN_STEP_SEC:  int = 5     # seconds shaved off per consecutive win

# ── Streak bonus ──────────────────────────────────────────────────────────────
_STREAK_BONUS_PER_WIN: float = 0.002   # +0.2 % of size per consecutive win
_STREAK_BONUS_MAX:     float = 0.10    # cap bonus at +10 % of computed size

# ── Micro-cap sizing (account_balance < _MICRO_CAP_MAX_BALANCE) ───────────────
# Source: Apr 2026 TRE micro-cap position sizing blueprint.
# Friction model: taker fee 0.62 % + spread 0.40 % + slippage 0.20 % + buffer 1 %
# Sizing formula: (balance × 1 %) / friction, hard-capped at 35 % of balance.
_MICRO_CAP_MAX_BALANCE:  float = 100.0   # route accounts below this to micro-cap path
_MICRO_CAP_RISK_PCT:     float = 0.01    # 1 % account risk per trade
_MICRO_CAP_MAX_POS_PCT:  float = 0.35    # 35 % hard cap on micro-cap position
_MICRO_CAP_SL_FLOOR:     float = 0.015   # 1.5 % SL floor on position value
_MICRO_CAP_TP1_FLOOR:    float = 0.035   # 3.5 % TP1 floor
_MICRO_CAP_FEE_DEFAULT:  float = 0.0062  # 0.62 % default taker fee
_MICRO_CAP_SPREAD:       float = 0.004   # 0.40 % spread
_MICRO_CAP_SLIPPAGE:     float = 0.002   # 0.20 % slippage
_MICRO_CAP_BUFFER:       float = 0.010   # 1.00 % profit safety buffer
_MICRO_CAP_NET_MIN:      float = 0.012   # veto when net TP − friction < 1.2 %
_MICRO_CAP_ATR_BASELINE: float = 0.020   # 2 % ATR baseline for volatility scalar
_MICRO_CAP_TP2_DEFAULT:  float = 0.045   # default TP2 level (4.5 %)
_MICRO_CAP_TP3_DEFAULT:  float = 0.070   # default TP3 level (7.0 %)
_MICRO_CAP_EPSILON:      float = 1e-6    # guard against division-by-zero in scalars


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


def _get_broker_fee(broker: Any, symbol: str) -> float:
    """
    Query the live broker for its taker fee on *symbol*.

    Falls back to the default 0.62 % when the broker is unavailable or
    returns an invalid value.
    """
    if broker is not None:
        try:
            fee = broker.get_fee(symbol)
            if fee and fee > 0:
                return float(fee)
        except Exception as exc:
            logger.debug("broker.get_fee(%s) unavailable: %s", symbol, exc)
    return _MICRO_CAP_FEE_DEFAULT


# ─────────────────────────────────────────────────────────────────────────────
# Micro-cap allocator  (balance < _MICRO_CAP_MAX_BALANCE)
# ─────────────────────────────────────────────────────────────────────────────

def _micro_cap_allocate(
    account_balance: float,
    symbol: str,
    broker_name: str,
    analysis: Dict[str, Any],
    broker: Any,
    streak: int,
    last_trade_ts: Optional[float],
) -> Optional[Dict[str, Any]]:
    """
    Direct TRE-aware sizing for micro-cap accounts (balance < $100).

    Implements the Apr 2026 micro-cap sizing blueprint:

    1. **Adaptive cooldown gate** — same formula as the standard path; veto
       while cooldown is active.
    2. **Fee-aware friction** — live ``broker.get_fee()`` + spread + slippage +
       buffer; fall back to 0.62 % default when unavailable.
    3. **Kelly-inspired sizing** — ``(balance × 1 %) / friction``, hard-capped
       at 35 % of balance.
    4. **Streak bonus** — +0.2 %/win up to +10 % of computed size.
    5. **ATR volatility scalar** — inverse relationship: higher ATR → smaller
       position (constant dollar risk).  Normalised to ``baseline / atr``,
       capped at 1.0 so low-vol markets never inflate size.
    6. **Net-profit veto** — skip when ``TP1 − (fee + spread + slippage)`` is
       below the 1.2 % floor.
    7. **Execution dict** — includes multi-level TP keys (tp1/tp2/tp3),
       ``post_only=True`` for Kraken limit orders, and diagnostic fields
       (``streak_bonus_applied``, ``net_profit_pct``, ``micro_cap=True``).

    Parameters
    ----------
    account_balance : float
        Current free balance in USD (expected < $100).
    symbol : str
        Trading pair.
    broker_name : str
        Lowercase broker identifier.
    analysis : dict
        Output of ``apex.analyze_market()``.  Keys consumed:
        ``atr_pct``, ``tp1_pct`` / ``profit_target_pct``, ``tp2_pct``,
        ``tp3_pct``, ``sl_pct`` / ``stop_loss_pct``, ``entry_price``.
    broker : object, optional
        Broker instance — used for live fee query.
    streak : int
        Consecutive winning trades since last loss.
    last_trade_ts : float or None
        Unix timestamp of the last trade on this symbol.

    Returns
    -------
    dict or None
        Execution-ready dict, or ``None`` when the trade is vetoed.
    """
    _a = analysis or {}

    # ── 1. Adaptive cooldown gate ─────────────────────────────────────────────
    _base = int(os.environ.get("NIJA_COOLDOWN_BASE_SEC", str(_COOLDOWN_BASE_SEC)))
    _step = int(os.environ.get("NIJA_COOLDOWN_STEP_SEC", str(_COOLDOWN_STEP_SEC)))
    cooldown_sec = max(_COOLDOWN_MIN_SEC, min(_COOLDOWN_MAX_SEC, _base - streak * _step))

    if last_trade_ts and last_trade_ts > 0:
        elapsed = time.time() - last_trade_ts
        if elapsed < cooldown_sec:
            remaining = cooldown_sec - elapsed
            logger.info(
                "⏱️  Cooldown active for %s (micro-cap) — %ds remaining of %ds (streak=%d)",
                symbol, int(remaining), cooldown_sec, streak,
            )
            return None

    # ── 2. Fee-aware friction model ───────────────────────────────────────────
    fee = _get_broker_fee(broker, symbol)
    friction = fee + _MICRO_CAP_SPREAD + _MICRO_CAP_SLIPPAGE + _MICRO_CAP_BUFFER

    # ── 3. Kelly-inspired base sizing ─────────────────────────────────────────
    # position = (balance × risk_pct) / friction, capped at balance × max_pos_pct
    position_value = (account_balance * _MICRO_CAP_RISK_PCT) / max(friction, _MICRO_CAP_EPSILON)
    position_value = min(position_value, account_balance * _MICRO_CAP_MAX_POS_PCT)

    # ── 4. Streak bonus (+0.2 %/win, capped at +10 %) ────────────────────────
    streak_bonus_pct = min(_STREAK_BONUS_MAX, max(0, streak) * _STREAK_BONUS_PER_WIN)
    if streak_bonus_pct > 0:
        pre_bonus = position_value
        position_value *= (1.0 + streak_bonus_pct)
        logger.info(
            "🔥 Micro-cap streak bonus ×%d on %s: $%.2f → $%.2f (+%.1f%%)",
            streak, symbol, pre_bonus, position_value, streak_bonus_pct * 100,
        )

    # ── 5. ATR volatility scalar (inverse: higher vol → smaller position) ────
    # Normalised so ATR = baseline (2 %) → scalar = 1.0; scales down above that.
    atr_raw = float(_a.get("atr_pct", _MICRO_CAP_ATR_BASELINE))
    atr_scalar = min(1.0, _MICRO_CAP_ATR_BASELINE / max(atr_raw, _MICRO_CAP_EPSILON))
    if atr_scalar < 1.0:
        logger.debug(
            "📉 ATR scalar %.3f applied to %s (ATR=%.2f%% > baseline %.2f%%)",
            atr_scalar, symbol, atr_raw * 100, _MICRO_CAP_ATR_BASELINE * 100,
        )
    position_value *= atr_scalar

    # ── 6. Net-profit veto ────────────────────────────────────────────────────
    # Use the raw analysis TP for the veto — floor only applies to the order target.
    tp1_raw = float(_a.get("tp1_pct", _a.get("profit_target_pct", _MICRO_CAP_TP1_FLOOR)))
    net_profit_pct = tp1_raw - (fee + _MICRO_CAP_SPREAD + _MICRO_CAP_SLIPPAGE)
    if net_profit_pct < _MICRO_CAP_NET_MIN:
        logger.info(
            "⚠️  allocate_capital: %s vetoed (micro-cap) — net TP %.2f%% < %.2f%% floor "
            "(TP1=%.2f%%, friction=%.2f%%)",
            symbol, net_profit_pct * 100, _MICRO_CAP_NET_MIN * 100,
            tp1_raw * 100, (fee + _MICRO_CAP_SPREAD + _MICRO_CAP_SLIPPAGE) * 100,
        )
        return None
    # Floor the execution target after passing the veto
    tp1 = max(tp1_raw, _MICRO_CAP_TP1_FLOOR)

    # ── 7. SL floor and broker minimum check ─────────────────────────────────
    sl = max(
        float(_a.get("sl_pct", _a.get("stop_loss_pct", _MICRO_CAP_SL_FLOOR))),
        _MICRO_CAP_SL_FLOOR,
    )
    # Re-apply hard cap after streak bonus and ATR scalar to guarantee ≤ 35 %
    position_value = min(position_value, account_balance * _MICRO_CAP_MAX_POS_PCT)
    position_value = math.floor(position_value * 100) / 100

    tier_min = _get_tier_min_trade(broker_name)
    if position_value < tier_min:
        logger.info(
            "📊 allocate_capital: %s VETOED (micro-cap) — size $%.2f < broker min $%.2f (%s)",
            symbol, position_value, tier_min, broker_name,
        )
        return None

    logger.info(
        "📊 Micro-cap position: $%.2f (streak=%d, bonus=+%.1f%%, atr×%.3f, cd=%ds) [%s]",
        position_value, streak, streak_bonus_pct * 100, atr_scalar, cooldown_sec, symbol,
    )

    return {
        "symbol":               symbol,
        "broker":               broker_name,
        "size_usd":             position_value,
        # Backward-compatible TP/SL keys (used by existing execution engine)
        "take_profit_pct":      tp1,
        "stop_loss_pct":        sl,
        "entry_price":          float(_a.get("entry_price", 0.0)),
        "cooldown_sec":         cooldown_sec,
        "streak":               streak,
        # Multi-level TP (blueprint extension)
        "tp1_pct":              tp1,
        "tp2_pct":              float(_a.get("tp2_pct", _MICRO_CAP_TP2_DEFAULT)),
        "tp3_pct":              float(_a.get("tp3_pct", _MICRO_CAP_TP3_DEFAULT)),
        "sl_pct":               sl,
        # Execution metadata
        "ordertype":            "limit",
        "post_only":            broker_name.lower() == "kraken",
        # Diagnostics
        "streak_bonus_applied": streak_bonus_pct,
        "net_profit_pct":       net_profit_pct,
        "micro_cap":            True,
    }


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
) -> Optional[Dict[str, Any]]:
    """
    High-level capital allocator — execution-ready position dict or None.

    Routes micro-cap accounts (balance < $100) to :func:`_micro_cap_allocate`,
    which uses a fee-aware Kelly formula, ATR volatility scalar, streak bonus,
    and multi-level TP.  Larger accounts use the standard TRE path below.

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
        ``atr_pct``, ``stop_loss_pct``, ``profit_target_pct``, ``entry_price``.
    broker : object, optional
        Broker instance — used for live price lookup when *entry_price* is
        missing from *analysis*.
    streak : int
        Consecutive winning trades since last loss (0 = no streak / cold).
    last_trade_ts : float or None
        Unix timestamp of the last trade on *symbol* (``time.time()`` style).
        Pass ``None`` or ``0`` to skip the cooldown gate.

    Returns
    -------
    dict or None
        Execution dict with keys ``symbol``, ``broker``, ``size_usd``,
        ``stop_loss_pct``, ``take_profit_pct``, ``entry_price``,
        ``cooldown_sec``, ``streak``.
        Returns ``None`` when the trade is vetoed (cooldown active, size ≤ 0,
        or net profit too low after fees).
    """
    _a = analysis or {}

    # ── 0. Route micro-cap accounts to the direct fee-aware sizing path ───────
    if account_balance < _MICRO_CAP_MAX_BALANCE:
        return _micro_cap_allocate(
            account_balance=account_balance,
            symbol=symbol,
            broker_name=broker_name,
            analysis=_a,
            broker=broker,
            streak=streak,
            last_trade_ts=last_trade_ts,
        )

    atr = float(_a.get("atr_pct",           0.02))
    sl  = float(_a.get("stop_loss_pct",      0.02))
    tp  = float(_a.get("profit_target_pct",  0.035))
    ep  = float(_a.get("entry_price",        0.0))

    # ── 1. Compute raw TRE size ───────────────────────────────────────────────
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

    # ── 4. Final hard cap — never exceed max_position_pct of balance ──────────
    max_position = float(os.environ.get("NIJA_TRE_MAX_POSITION_PCT", str(_DEFAULT_MAX_POSITION_PCT)))
    cap = math.floor(account_balance * max_position * 100) / 100
    if size > cap:
        logger.debug("allocate_capital: %s size capped $%.2f → $%.2f (%.0f%% of balance)", symbol, size, cap, max_position * 100)
        size = cap

    logger.info(
        "📊 Position size computed: $%.2f  [%s | streak=%d | cd=%ds]",
        size, symbol, streak, cooldown_sec,
    )

    return {
        "symbol":          symbol,
        "broker":          broker_name,
        "size_usd":        size,
        "stop_loss_pct":   sl,
        "take_profit_pct": tp,
        "entry_price":     ep,
        "cooldown_sec":    cooldown_sec,
        "streak":          streak,
    }
