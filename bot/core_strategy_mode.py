"""
NIJA Core Strategy Mode
========================

Activates a focused, institutional-grade trading profile scoped to the two
highest-liquidity markets on Coinbase (BTC-USD and ETH-USD) when the
environment variable ``NIJA_CORE_STRATEGY_MODE=true`` is set.

Features
--------
* **Symbol scope** — only BTC-USD and ETH-USD are scanned and traded.
* **No-leverage enforcement** — position size is clamped to account balance
  (1× max) when ``NIJA_CORE_STRATEGY_MODE=true`` *or* when the standalone
  ``NIJA_NO_LEVERAGE=true`` flag is set.
* **Tighter institutional risk caps** — risk-per-trade 0.75% (vs 1.5%
  default), daily loss cap 2.0% (vs 3.0%), max 3 concurrent positions,
  max 10% of balance per trade.
* **Trend-filtered mean-reversion gate** — in strong-trend / expansion
  regimes, counter-trend entries (e.g. RSI > 65 long or RSI < 35 short)
  are blocked so the bot only fades the move when the regime actually
  supports mean-reversion.
* **ATR-aware exits** — a tighter default ATR multiplier (1.3×) is exposed
  for use by the exit-config layer when sizing stops for BTC/ETH.

All features are **opt-in via env flags** so existing behaviour is
completely unaffected until a flag is explicitly set.

Environment variables
---------------------
``NIJA_CORE_STRATEGY_MODE``
    ``true / 1 / yes``  — activates the full core strategy profile.
    Defaults to ``false``.

``NIJA_NO_LEVERAGE``
    ``true / 1 / yes``  — standalone no-leverage clamp only (no symbol
    scoping or tighter risk caps).  Automatically implied when
    ``NIJA_CORE_STRATEGY_MODE`` is active.

Author: NIJA Trading Systems
Version: 1.0
Date: May 2026
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import FrozenSet

logger = logging.getLogger("nija.core_strategy_mode")

# ---------------------------------------------------------------------------
# Environment flags  (evaluated once at import time, matching project style)
# ---------------------------------------------------------------------------

_CORE_MODE: bool = os.getenv(
    "NIJA_CORE_STRATEGY_MODE", "false"
).strip().lower() in ("true", "1", "yes")

_NO_LEVERAGE: bool = os.getenv(
    "NIJA_NO_LEVERAGE", "false"
).strip().lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Symbol universe
# ---------------------------------------------------------------------------

# The two symbols eligible for trading when core mode is active.
CORE_SYMBOLS: FrozenSet[str] = frozenset({"BTC-USD", "ETH-USD"})

# ---------------------------------------------------------------------------
# Risk caps applied when core mode is active
# ---------------------------------------------------------------------------

# Risk per trade — 0.75% vs the default 1.5% in risk_manager.py
CORE_RISK_PCT: float = 0.0075

# Daily loss cap — 2.0% vs 3.0% (HARD_DAILY_LOSS_PCT in risk_manager.py)
CORE_DAILY_LOSS_PCT: float = 2.0

# Maximum concurrent open positions (0 = not restricted by core mode)
CORE_MAX_POSITIONS: int = 3

# Maximum single-position size as a fraction of account balance
CORE_MAX_POSITION_PCT: float = 0.10   # 10% vs 15% default

# ATR multiplier for stop-loss sizing on BTC/ETH (tighter than default 1.5)
CORE_ATR_MULTIPLIER: float = 1.3

# ---------------------------------------------------------------------------
# Regime sets used for the counter-trend gate
# ---------------------------------------------------------------------------

# Regimes where counter-trend (mean-reversion) entries are *blocked*.
# In a confirmed trend the bot should only ride the trend, not fade it.
_STRONG_TREND_REGIMES: FrozenSet[str] = frozenset(
    {"strong_trend", "expansion", "trending"}
)

# Regimes where mean-reversion entries are explicitly *permitted*.
_MEAN_REVERSION_REGIMES: FrozenSet[str] = frozenset(
    {"ranging", "consolidation", "mean_reversion"}
)

# RSI thresholds that define "counter-trend" in a trending regime.
# A long signal is counter-trend when RSI_14 > this value (overbought).
# A short signal is counter-trend when RSI_14 < this value (oversold).
_COUNTER_TREND_RSI_LONG_THRESHOLD: float = 65.0
_COUNTER_TREND_RSI_SHORT_THRESHOLD: float = 35.0


# ---------------------------------------------------------------------------
# Public config dataclass
# ---------------------------------------------------------------------------

@dataclass
class CoreModeConfig:
    """
    Resolved core mode configuration snapshot for one trading cycle.

    Consumers should call ``get_core_mode_config()`` once and store the
    result locally rather than calling it repeatedly in a tight loop.
    """

    active: bool
    """True when NIJA_CORE_STRATEGY_MODE is enabled."""

    no_leverage: bool
    """True when any form of no-leverage enforcement is active."""

    allowed_symbols: FrozenSet[str]
    """Permitted trading symbols.  Empty frozenset means 'all'."""

    risk_pct: float
    """Risk per trade as a fraction of account balance (e.g. 0.0075 = 0.75%)."""

    daily_loss_pct: float
    """Daily loss cap percentage (e.g. 2.0 = 2.0%)."""

    max_positions: int
    """Maximum concurrent open positions (0 = no restriction from core mode)."""

    max_position_pct: float
    """Maximum single-position size as a fraction of account balance."""

    atr_multiplier: float
    """ATR multiplier for stop-loss distance computation."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_core_mode_config() -> CoreModeConfig:
    """Return a fully-resolved ``CoreModeConfig`` for the current env."""
    return CoreModeConfig(
        active=_CORE_MODE,
        no_leverage=_CORE_MODE or _NO_LEVERAGE,
        allowed_symbols=CORE_SYMBOLS if _CORE_MODE else frozenset(),
        risk_pct=CORE_RISK_PCT if _CORE_MODE else 0.015,
        daily_loss_pct=CORE_DAILY_LOSS_PCT if _CORE_MODE else 3.0,
        max_positions=CORE_MAX_POSITIONS if _CORE_MODE else 0,
        max_position_pct=CORE_MAX_POSITION_PCT if _CORE_MODE else 0.15,
        atr_multiplier=CORE_ATR_MULTIPLIER if _CORE_MODE else 1.5,
    )


def is_core_mode_active() -> bool:
    """Return True when ``NIJA_CORE_STRATEGY_MODE`` is enabled."""
    return _CORE_MODE


def is_no_leverage_active() -> bool:
    """
    Return True when any no-leverage enforcement is in effect.

    This includes both ``NIJA_CORE_STRATEGY_MODE`` (which implies no
    leverage) and the standalone ``NIJA_NO_LEVERAGE`` flag.
    """
    return _CORE_MODE or _NO_LEVERAGE


def is_symbol_allowed(symbol: str) -> bool:
    """
    Return True when *symbol* is permitted in the current trading mode.

    When ``NIJA_CORE_STRATEGY_MODE`` is **not** active this always returns
    True (all symbols permitted, identical to the previous behaviour).
    When active, only ``BTC-USD`` and ``ETH-USD`` pass.
    """
    if not _CORE_MODE:
        return True
    return symbol.upper() in CORE_SYMBOLS


def is_counter_trend_blocked(
    regime: str,
    side: str,
    rsi_14: float,
) -> bool:
    """
    Return True when a counter-trend entry should be blocked.

    In strong-trend / expansion regimes the bot must *not* fade the move.
    Counter-trend is defined as:
    - ``side="long"``  and ``rsi_14 > 65`` (overbought entry against trend)
    - ``side="short"`` and ``rsi_14 < 35`` (oversold entry against trend)

    Only applied when ``NIJA_CORE_STRATEGY_MODE`` is active.

    Args:
        regime:  Current regime label string (any case, spaces OK).
        side:    Trade direction — ``"long"`` or ``"short"``.
        rsi_14:  Most recent RSI-14 value (0–100).

    Returns:
        True if the entry should be blocked; False otherwise.
    """
    if not _CORE_MODE:
        return False

    regime_key = str(regime).lower().replace(" ", "_")
    if regime_key not in _STRONG_TREND_REGIMES:
        return False

    if side == "long" and rsi_14 > _COUNTER_TREND_RSI_LONG_THRESHOLD:
        return True
    if side == "short" and rsi_14 < _COUNTER_TREND_RSI_SHORT_THRESHOLD:
        return True
    return False


def clamp_no_leverage(
    position_size_usd: float,
    account_balance: float,
) -> float:
    """
    Clamp *position_size_usd* to at most *account_balance* (1× max leverage).

    No-op when no-leverage enforcement is inactive.

    Args:
        position_size_usd:  Computed position size in USD.
        account_balance:    Available account balance in USD.

    Returns:
        Adjusted position size (≤ account_balance when enforcement is active).
    """
    if not is_no_leverage_active():
        return position_size_usd

    if account_balance <= 0:
        return position_size_usd

    if position_size_usd > account_balance:
        logger.info(
            "🔒 NO-LEVERAGE CLAMP: position $%.2f → $%.2f "
            "(balance=$%.2f, 1× max leverage)",
            position_size_usd,
            account_balance,
            account_balance,
        )
        return account_balance

    return position_size_usd


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

if _CORE_MODE:
    logger.info(
        "🎯 CORE STRATEGY MODE ACTIVE | symbols=%s | risk=%.2f%% | "
        "daily_loss=%.1f%% | max_pos=%d | max_pos_pct=%.0f%% | "
        "atr_mult=%.1f× | no_leverage=%s",
        list(CORE_SYMBOLS),
        CORE_RISK_PCT * 100,
        CORE_DAILY_LOSS_PCT,
        CORE_MAX_POSITIONS,
        CORE_MAX_POSITION_PCT * 100,
        CORE_ATR_MULTIPLIER,
        "YES",
    )
elif _NO_LEVERAGE:
    logger.info("🔒 NO-LEVERAGE MODE ACTIVE (standalone) — position sizes clamped to 1× account balance")
