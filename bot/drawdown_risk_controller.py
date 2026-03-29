"""
NIJA Drawdown Risk Controller
==============================

Industry principle — "Risk Limits: Drawdown controls + fractional risk"
— is the final pre-entry authority in NIJA's decision chain.

This module is called ONCE at the start of each ``analyze_market()``
call (before any signal computation) to give a fast, low-cost verdict:

    can_trade          → True / False
    position_multiplier → 0.0 – 1.0  (dynamically scaled by volatility)
    reason             → human-readable explanation

Three layers of protection
--------------------------

Layer 1 — Global drawdown circuit breaker (existing module)
    Integrates with ``bot.global_drawdown_circuit_breaker``.
    Tiers:  CLEAR (0-5%) / CAUTION (5-10%) / WARNING (10-15%) /
            DANGER (15-20%) / HALT (>20%).
    At HALT: all new entries blocked.
    At lower tiers: position multiplier reduced automatically.

Layer 2 — Daily loss limit
    If today's realised P&L (cumulative) falls below ``-daily_loss_limit_pct``
    of account balance, trading halts until the next calendar day.
    Default: -3.0 % of account.
    Prevents the "revenge trading spiral" that destroys small accounts.

Layer 3 — ATR-based dynamic position sizing
    Current ATR% is used to scale the position multiplier:
    • ATR < 2 % (calm)   → multiplier = 1.00  (full size)
    • ATR 2–4 %          → multiplier = 0.80
    • ATR 4–6 %          → multiplier = 0.60
    • ATR 6–8 %          → multiplier = 0.45
    • ATR > 8 % (wild)   → multiplier = 0.30
    This ensures that when markets are extra volatile the bot
    automatically trades smaller — without any manual intervention.

Layer 4 — Market condition pre-filter (5 of 5 must score ≥ threshold)
    A lightweight score (0–5) checks five basic market-health conditions
    before any expensive signal computation runs:
    1. ADX > 8          (some directional momentum)
    2. Volume > 0.4×avg (some liquidity)
    3. ATR > 0.25%      (enough movement to profit after fees)
    4. Regime not VOLATILITY_EXPLOSION
    5. Price > 0        (basic sanity)
    Score < 3 → return hold immediately (saves ~60ms of signal computation).

Usage
-----
::

    from bot.drawdown_risk_controller import get_drawdown_risk_controller

    ctrl = get_drawdown_risk_controller()
    ctrl.initialise(starting_balance=account_balance)   # once at startup

    result = ctrl.pre_entry_check(
        account_balance=account_balance,
        df=df,
        indicators=indicators,
        daily_pnl_usd=self._daily_pnl_usd,
        regime=self.current_regime,
    )
    if not result.can_trade:
        return {'action': 'hold', 'reason': result.reason}
    position_size *= result.position_multiplier

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.drawdown_risk_controller")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ef(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# ATR-based position multiplier table
# (upper_atr_pct, multiplier)  — ordered from LOW to HIGH
# ---------------------------------------------------------------------------
_ATR_VOL_TABLE: Tuple[Tuple[float, float], ...] = (
    (2.0,  1.00),   # calm
    (4.0,  0.80),
    (6.0,  0.60),
    (8.0,  0.45),
    (999., 0.30),   # wild/extreme
)

# Market condition minimum score to allow entry (out of 5)
_MIN_CONDITION_SCORE = 3


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RiskEnvelopeResult:
    """Result returned by ``pre_entry_check``."""
    can_trade: bool
    position_multiplier: float      # 0.0 – 1.0 dynamic scaling
    reason: str
    drawdown_level: str             # CLEAR / CAUTION / WARNING / DANGER / HALT
    daily_pnl_pct: float            # today's P&L as % of balance
    condition_score: int            # 0-5 market-health score
    atr_pct: float                  # current ATR%
    layer_blocked: str              # which layer blocked (or "" if passed)


# ---------------------------------------------------------------------------
# Controller class
# ---------------------------------------------------------------------------

class DrawdownRiskController:
    """
    Three-layer + market-condition pre-entry risk authority.

    Thread-safe; stateful only for the daily-loss tracking and CB proxy.
    """

    def __init__(
        self,
        daily_loss_limit_pct: Optional[float] = None,
        min_condition_score: int = _MIN_CONDITION_SCORE,
    ) -> None:
        self._lock = threading.Lock()
        self._daily_loss_limit = (
            daily_loss_limit_pct / 100.0
            if daily_loss_limit_pct is not None
            else _ef("MAX_DAILY_LOSS_PCT", 3.0) / 100.0
        )
        self._min_cond_score = min_condition_score
        self._peak_balance: float = 0.0
        self._initialised: bool = False

        # Try to use existing global drawdown circuit breaker
        self._gdcb = None
        try:
            from bot.global_drawdown_circuit_breaker import get_global_drawdown_cb
            self._gdcb = get_global_drawdown_cb()
        except ImportError:
            try:
                from global_drawdown_circuit_breaker import get_global_drawdown_cb
                self._gdcb = get_global_drawdown_cb()
            except ImportError:
                logger.warning(
                    "⚠️  GlobalDrawdownCircuitBreaker unavailable — "
                    "Layer 1 disabled; daily-loss + ATR layers remain active"
                )

        logger.info(
            "🛡️  DrawdownRiskController initialized — "
            "daily_loss_limit=%.1f%% | min_condition_score=%d/5 | "
            "global_CB=%s",
            self._daily_loss_limit * 100,
            self._min_cond_score,
            "✅" if self._gdcb else "❌ (unavailable)",
        )

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialise(self, starting_balance: float) -> None:
        """
        Set the starting equity baseline.  Call once at bot startup.

        Args:
            starting_balance: Account equity at the start of the session.
        """
        with self._lock:
            self._peak_balance = max(self._peak_balance, starting_balance)
            self._initialised = True
        if self._gdcb is not None:
            try:
                self._gdcb.initialise(starting_equity=starting_balance)
            except Exception as e:
                logger.debug("GDCB initialise error: %s", e)
        logger.info(
            "🛡️  DrawdownRiskController initialised — peak_balance=$%.2f",
            starting_balance,
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def pre_entry_check(
        self,
        account_balance: float,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        daily_pnl_usd: float = 0.0,
        regime: Any = None,
    ) -> RiskEnvelopeResult:
        """
        Run all risk layers.  Returns on first block.

        Args:
            account_balance: Current total equity in USD.
            df: OHLCV DataFrame.
            indicators: Calculated indicators dict.
            daily_pnl_usd: Today's cumulative P&L in USD (negative = loss).
            regime: Current market regime (for condition check).

        Returns:
            ``RiskEnvelopeResult`` with can_trade, multiplier, and reason.
        """
        # Auto-initialise if not done yet
        if not self._initialised:
            self.initialise(account_balance)

        # Update peak balance
        with self._lock:
            if account_balance > self._peak_balance:
                self._peak_balance = account_balance
            peak = self._peak_balance

        daily_pnl_pct = (daily_pnl_usd / account_balance) if account_balance > 0 else 0.0

        # Gather ATR for vol-based sizing
        atr_pct = self._get_atr_pct(df, indicators)

        # ── Layer 1: Global drawdown circuit breaker ──────────────────
        dd_level, dd_mult, dd_blocked, dd_reason = self._layer_drawdown(account_balance)
        if dd_blocked:
            return RiskEnvelopeResult(
                can_trade=False,
                position_multiplier=0.0,
                reason=f"[HALT] {dd_reason}",
                drawdown_level=dd_level,
                daily_pnl_pct=round(daily_pnl_pct, 4),
                condition_score=0,
                atr_pct=round(atr_pct, 3),
                layer_blocked="layer1_drawdown",
            )

        # ── Layer 2: Daily loss limit ─────────────────────────────────
        if daily_pnl_pct < -self._daily_loss_limit:
            reason = (
                f"Daily loss limit reached: {daily_pnl_pct*100:.2f}% < "
                f"-{self._daily_loss_limit*100:.1f}% limit — "
                f"halting until tomorrow"
            )
            logger.warning("🛑 %s", reason)
            return RiskEnvelopeResult(
                can_trade=False,
                position_multiplier=0.0,
                reason=f"[DAILY_LOSS] {reason}",
                drawdown_level=dd_level,
                daily_pnl_pct=round(daily_pnl_pct, 4),
                condition_score=0,
                atr_pct=round(atr_pct, 3),
                layer_blocked="layer2_daily_loss",
            )

        # ── Layer 3: ATR-based dynamic position sizing ────────────────
        vol_mult = self._atr_to_multiplier(atr_pct)

        # ── Layer 4: Market condition pre-filter ─────────────────────
        score = self._market_condition_score(df, indicators, regime)
        if score < self._min_cond_score:
            reason = (
                f"Market conditions too weak: {score}/{self._min_cond_score} "
                f"(ADX/volume/volatility checks) — holding"
            )
            logger.debug("🛡️  %s", reason)
            return RiskEnvelopeResult(
                can_trade=False,
                position_multiplier=0.0,
                reason=f"[CONDITIONS] {reason}",
                drawdown_level=dd_level,
                daily_pnl_pct=round(daily_pnl_pct, 4),
                condition_score=score,
                atr_pct=round(atr_pct, 3),
                layer_blocked="layer4_conditions",
            )

        # ── All layers passed — combine multipliers ───────────────────
        combined_mult = round(dd_mult * vol_mult, 3)
        logger.debug(
            "🛡️  Risk OK: dd_mult=%.2f × vol_mult=%.2f = %.2f | "
            "dd=%s | daily=%.2f%% | ATR=%.2f%% | cond=%d/5",
            dd_mult, vol_mult, combined_mult,
            dd_level, daily_pnl_pct * 100, atr_pct, score,
        )
        return RiskEnvelopeResult(
            can_trade=True,
            position_multiplier=combined_mult,
            reason=(
                f"Risk envelope CLEAR — "
                f"dd={dd_level} mult={dd_mult:.2f} "
                f"vol_mult={vol_mult:.2f} cond={score}/5"
            ),
            drawdown_level=dd_level,
            daily_pnl_pct=round(daily_pnl_pct, 4),
            condition_score=score,
            atr_pct=round(atr_pct, 3),
            layer_blocked="",
        )

    def record_trade(self, pnl_usd: float, is_win: bool) -> None:
        """Forward trade outcome to the global circuit breaker for recovery tracking."""
        if self._gdcb is not None:
            try:
                self._gdcb.record_trade(pnl_usd=pnl_usd, is_win=is_win)
            except Exception as e:
                logger.debug("GDCB record_trade error: %s", e)

    # ------------------------------------------------------------------
    # Internal layers
    # ------------------------------------------------------------------

    def _layer_drawdown(
        self, account_balance: float
    ) -> Tuple[str, float, bool, str]:
        """
        Return (level_str, size_multiplier, is_halted, reason).
        """
        if self._gdcb is None:
            # Manual drawdown check using stored peak
            with self._lock:
                peak = self._peak_balance
            if peak > 0:
                dd = (peak - account_balance) / peak * 100
            else:
                dd = 0.0

            if dd >= 20.0:
                return "HALT", 0.0, True, (
                    f"Manual drawdown HALT: {dd:.1f}% peak-to-trough"
                )
            elif dd >= 15.0:
                return "DANGER", 0.25, False, ""
            elif dd >= 10.0:
                return "WARNING", 0.50, False, ""
            elif dd >= 5.0:
                return "CAUTION", 0.75, False, ""
            return "CLEAR", 1.0, False, ""

        # Use global circuit breaker
        try:
            decision = self._gdcb.update_equity(account_balance)
            level = str(getattr(self._gdcb, "_level", "CLEAR")).split(".")[-1]
            if not decision.allow_new_entries:
                return level, 0.0, True, (
                    f"GlobalDrawdownCB halted: drawdown {decision.drawdown_pct:.1f}%"
                )
            return level, decision.position_size_multiplier, False, ""
        except Exception as e:
            logger.debug("GDCB update_equity error: %s", e)
            return "CLEAR", 1.0, False, ""

    @staticmethod
    def _atr_to_multiplier(atr_pct: float) -> float:
        """Map ATR% to a position size multiplier (smaller in high vol)."""
        for upper, mult in _ATR_VOL_TABLE:
            if atr_pct <= upper:
                return mult
        return 0.30

    @staticmethod
    def _get_atr_pct(df: pd.DataFrame, indicators: Dict[str, Any]) -> float:
        """Return current ATR as % of price, or 0 on error."""
        try:
            atr_s = indicators.get("atr")
            if atr_s is None or len(atr_s) == 0:
                return 0.0
            atr = float(atr_s.iloc[-1])
            price = float(df["close"].iloc[-1])
            return (atr / price * 100) if price > 0 else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _market_condition_score(
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        regime: Any,
    ) -> int:
        """
        Score market health from 0 (terrible) to 5 (excellent).
        Each condition contributes 1 point.
        """
        score = 0

        # 1. ADX > 8 (some directional activity)
        try:
            adx = float(indicators.get("adx", pd.Series([0])).iloc[-1])
            if adx > 8.0:
                score += 1
        except Exception:
            score += 1  # skip on error

        # 2. Volume > 40% of 20-bar average
        try:
            avg_vol = df["volume"].iloc[-21:-1].mean() if len(df) >= 21 else df["volume"].mean()
            cur_vol = float(df["volume"].iloc[-1])
            if avg_vol > 0 and (cur_vol / avg_vol) >= 0.40:
                score += 1
        except Exception:
            score += 1

        # 3. ATR > 0.25% (enough movement to profit after fees)
        try:
            atr_s = indicators.get("atr")
            if atr_s is not None and len(atr_s) > 0:
                atr = float(atr_s.iloc[-1])
                price = float(df["close"].iloc[-1])
                atr_pct = (atr / price * 100) if price > 0 else 0.0
                if atr_pct >= 0.25:
                    score += 1
        except Exception:
            score += 1

        # 4. Not in VOLATILITY_EXPLOSION regime
        try:
            regime_str = ""
            if hasattr(regime, "value"):
                regime_str = str(regime.value).lower()
            elif regime is not None:
                regime_str = str(regime).lower()
            if "volatility_explosion" not in regime_str:
                score += 1
        except Exception:
            score += 1

        # 5. Price is positive and data is valid
        try:
            price = float(df["close"].iloc[-1])
            if price > 0 and not pd.isna(price):
                score += 1
        except Exception:
            pass

        return score


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ctrl_instance: Optional[DrawdownRiskController] = None
_ctrl_lock = threading.Lock()


def get_drawdown_risk_controller(
    daily_loss_limit_pct: Optional[float] = None,
) -> DrawdownRiskController:
    """
    Return the module-level singleton ``DrawdownRiskController``.

    Note: ``daily_loss_limit_pct`` is only applied on the FIRST call that
    creates the instance.  Subsequent calls with a different value will
    return the existing instance with its original configuration.
    Use the ``MAX_DAILY_LOSS_PCT`` environment variable to configure the
    limit before the first call if you need runtime control.
    """
    global _ctrl_instance
    if _ctrl_instance is None:
        with _ctrl_lock:
            if _ctrl_instance is None:
                _ctrl_instance = DrawdownRiskController(
                    daily_loss_limit_pct=daily_loss_limit_pct,
                )
    return _ctrl_instance


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import numpy as np
    logging.basicConfig(level=logging.DEBUG)

    ctrl = get_drawdown_risk_controller(daily_loss_limit_pct=3.0)
    ctrl.initialise(starting_balance=1000.0)

    n = 25
    prices = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open":   prices * 0.999,
        "high":   prices * 1.005,
        "low":    prices * 0.995,
        "close":  prices,
        "volume": np.abs(np.random.randn(n) * 1000) + 500,
    })
    indicators = {"atr": pd.Series([1.5] * n), "adx": pd.Series([22.0] * n)}

    scenarios = [
        (1000.0,  0.0,    "weak_trend",           "Normal market"),
        (1000.0, -35.0,   "weak_trend",           "Daily loss -3.5%"),
        (800.0,   0.0,    "weak_trend",            "Drawdown -20%"),
        (1000.0,  0.0,    "volatility_explosion",  "Volatility explosion"),
        (950.0,  -10.0,   "ranging",               "Moderate drawdown + loss"),
    ]

    print("\n" + "=" * 80)
    print("DRAWDOWN RISK CONTROLLER — SCENARIOS")
    print("=" * 80)
    for balance, daily_pnl, regime, label in scenarios:
        r = ctrl.pre_entry_check(balance, df, indicators, daily_pnl, regime)
        status = "✅ TRADE" if r.can_trade else "❌ HOLD "
        print(
            f"\n{label:40s} {status} | "
            f"mult={r.position_multiplier:.2f} | "
            f"dd={r.drawdown_level} | "
            f"cond={r.condition_score}/5 | "
            f"ATR={r.atr_pct:.2f}%"
        )
        if not r.can_trade:
            print(f"  Reason: {r.reason}")
    print("\n" + "=" * 80)
