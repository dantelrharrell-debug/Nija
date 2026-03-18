"""
NIJA Win Rate Maximizer
========================

Unified entry-gate that orchestrates three pillars designed to push win rate
from a raw 45–55 % baseline toward 65–70 %+:

  1. Trade Filtering  — multi-layer signal quality scoring that rejects setups
                        with poor trend alignment, insufficient volume, weak
                        momentum, or bad reward-to-risk ratios.

  2. Risk Caps        — hard per-session limits on daily loss (USD + %), max
                        drawdown, and consecutive losses that halt new entries
                        until the account recovers.

  3. Profit Consistency — rolling win-rate floor and per-symbol performance
                          memory that penalise chronically poor setups before
                          they erode the equity curve.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────┐
    │                   WinRateMaximizer                           │
    │                                                              │
    │  approve_trade(symbol, analysis, df, indicators, balance)    │
    │                                                              │
    │  ┌─────────────────────────────────────────────────────┐    │
    │  │ Layer 1 – Risk Caps                                  │    │
    │  │   • daily_loss_usd / daily_loss_pct exceeded → HALT  │    │
    │  │   • consecutive_losses ≥ cap → COOL-DOWN             │    │
    │  │   • drawdown ≥ max_drawdown_pct → HALT               │    │
    │  └─────────────────────────────────────────────────────┘    │
    │  ┌─────────────────────────────────────────────────────┐    │
    │  │ Layer 2 – Signal Quality Score (0–100)               │    │
    │  │   • trend_strength  (ADX + EMA alignment)  0–25 pts  │    │
    │  │   • volatility_fit  (ATR vs avg ATR)        0–25 pts  │    │
    │  │   • volume_confirm  (bar vol vs 20-avg)     0–25 pts  │    │
    │  │   • momentum_align  (RSI + MACD histogram)  0–25 pts  │    │
    │  │   Score ≥ SIGNAL_THRESHOLD (default 70) → pass        │    │
    │  └─────────────────────────────────────────────────────┘    │
    │  ┌─────────────────────────────────────────────────────┐    │
    │  │ Layer 3 – Profit Consistency Gate                    │    │
    │  │   • rolling win-rate (last N trades) ≥ floor         │    │
    │  │   • per-symbol rolling win-rate ≥ symbol floor       │    │
    │  └─────────────────────────────────────────────────────┘    │
    │                                                              │
    │  record_outcome(symbol, is_win, pnl_usd)                     │
    │  get_dashboard() → dict                                      │
    └──────────────────────────────────────────────────────────────┘

Integration
-----------
    from bot.win_rate_maximizer import get_win_rate_maximizer

    wmx = get_win_rate_maximizer()

    # Before entering a position:
    approved, reason, score = wmx.approve_trade(
        symbol="BTC-USD",
        analysis=analysis_dict,
        df=ohlcv_df,
        indicators=indicators_dict,
        account_balance=balance_usd,
    )
    if not approved:
        logger.info("Trade rejected by WinRateMaximizer: %s", reason)
        return

    # After closing a position:
    wmx.record_outcome(symbol="BTC-USD", is_win=True, pnl_usd=42.50)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.win_rate_maximizer")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Layer 1 – Risk Caps
DEFAULT_MAX_DAILY_LOSS_USD: float = 200.0    # hard stop in USD
DEFAULT_MAX_DAILY_LOSS_PCT: float = 0.05     # 5 % of starting balance
DEFAULT_MAX_CONSECUTIVE_LOSSES: int = 4      # cool-down after N straight losses
DEFAULT_MAX_DRAWDOWN_PCT: float = 0.10       # 10 % from session peak

# Layer 2 – Signal Quality
DEFAULT_SIGNAL_THRESHOLD: float = 70.0       # minimum score (0–100)

# Layer 3 – Profit Consistency
DEFAULT_WIN_RATE_WINDOW: int = 30            # rolling window (trades)
DEFAULT_MIN_WIN_RATE: float = 0.40           # 40 % floor (only gate after window filled)
DEFAULT_SYMBOL_WINDOW: int = 10              # per-symbol window
DEFAULT_MIN_SYMBOL_WIN_RATE: float = 0.30    # 30 % per-symbol floor


# ---------------------------------------------------------------------------
# Public data containers
# ---------------------------------------------------------------------------

@dataclass
class WinRateDecision:
    """Result of a single ``approve_trade`` call."""
    approved: bool
    reason: str
    score: float                   # signal quality score 0–100
    layer_rejected: str = ""       # "risk_caps" | "signal_quality" | "profit_consistency" | ""

    def __str__(self) -> str:
        status = "✅ APPROVED" if self.approved else "🚫 REJECTED"
        return f"{status} | score={self.score:.1f} | {self.reason}"


@dataclass
class WinRateStats:
    """Snapshot of the maximizer's current performance state."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    daily_pnl_usd: float = 0.0
    consecutive_losses: int = 0
    peak_balance: float = 0.0
    current_balance: float = 0.0
    drawdown_pct: float = 0.0
    session_halted: bool = False
    halt_reason: str = ""


# ---------------------------------------------------------------------------
# Internal helpers – signal quality scoring
# ---------------------------------------------------------------------------

def _score_trend_strength(indicators: dict, side: str) -> float:
    """ADX strength + EMA alignment → 0–25 pts."""
    score = 0.0
    try:
        adx_series = indicators.get("adx")
        adx = float(adx_series.iloc[-1]) if adx_series is not None and len(adx_series) > 0 else 0.0

        # ADX contribution (0–12.5)
        if adx >= 30:
            score += 12.5
        elif adx >= 20:
            score += 8.0
        elif adx >= 15:
            score += 5.0

        # EMA alignment contribution (0–12.5)
        ema9_s  = indicators.get("ema_9")
        ema21_s = indicators.get("ema_21")
        ema50_s = indicators.get("ema_50")
        if ema9_s is not None and ema21_s is not None and ema50_s is not None:
            ema9  = float(ema9_s.iloc[-1])
            ema21 = float(ema21_s.iloc[-1])
            ema50 = float(ema50_s.iloc[-1])
            if side == "long" and ema9 > ema21 > ema50:
                score += 12.5
            elif side == "short" and ema9 < ema21 < ema50:
                score += 12.5
            elif side == "long" and ema9 > ema21:
                score += 6.0
            elif side == "short" and ema9 < ema21:
                score += 6.0
    except Exception:
        pass
    return min(score, 25.0)


def _score_volatility(df: pd.DataFrame, indicators: dict) -> float:
    """ATR relative to its rolling mean → 0–25 pts (optimal = neither flat nor explosive)."""
    score = 0.0
    try:
        atr_series = indicators.get("atr")
        if atr_series is not None and len(atr_series) >= 14:
            atr_now  = float(atr_series.iloc[-1])
            atr_mean = float(atr_series.iloc[-14:].mean())
            if atr_mean <= 0:
                return 12.5   # neutral
            ratio = atr_now / atr_mean
            if 0.8 <= ratio <= 1.5:
                score = 25.0   # sweet spot
            elif 0.6 <= ratio < 0.8:
                score = 18.0
            elif 1.5 < ratio <= 2.5:
                score = 15.0
            else:
                score = 5.0    # flat or extreme
        else:
            score = 12.5       # neutral when insufficient data
    except Exception:
        score = 12.5
    return min(score, 25.0)


def _score_volume(df: pd.DataFrame) -> float:
    """Current bar volume vs 20-period average → 0–25 pts."""
    score = 0.0
    try:
        if "volume" in df.columns and len(df) >= 20:
            vol_now  = float(df["volume"].iloc[-1])
            vol_avg  = float(df["volume"].iloc[-20:].mean())
            if vol_avg <= 0:
                return 12.5
            ratio = vol_now / vol_avg
            if ratio >= 1.5:
                score = 25.0
            elif ratio >= 1.2:
                score = 18.0
            elif ratio >= 1.0:
                score = 12.0
            elif ratio >= 0.7:
                score = 6.0
            else:
                score = 0.0
        else:
            score = 12.5       # neutral when no volume data
    except Exception:
        score = 12.5
    return min(score, 25.0)


def _score_momentum(indicators: dict, side: str) -> float:
    """RSI position + MACD histogram confirmation → 0–25 pts."""
    score = 0.0
    try:
        rsi_series = indicators.get("rsi_9")
        if rsi_series is None:
            rsi_series = indicators.get("rsi_14")
        macd_series = indicators.get("macd_hist")

        rsi = float(rsi_series.iloc[-1]) if rsi_series is not None and len(rsi_series) > 0 else 50.0
        macd = float(macd_series.iloc[-1]) if macd_series is not None and len(macd_series) > 0 else 0.0

        # RSI contribution (0–12.5)
        if side == "long":
            if 45 <= rsi <= 65:
                score += 12.5      # ideal momentum zone
            elif 35 <= rsi < 45:
                score += 8.0       # recovering
            elif rsi > 65:
                score += 4.0       # overbought risk
        else:  # short
            if 35 <= rsi <= 55:
                score += 12.5
            elif 55 < rsi <= 65:
                score += 8.0
            elif rsi < 35:
                score += 4.0

        # MACD confirmation (0–12.5)
        if side == "long" and macd > 0:
            score += 12.5
        elif side == "short" and macd < 0:
            score += 12.5
        elif macd != 0:
            score += 3.0           # wrong direction — partial
    except Exception:
        score = 12.5               # neutral
    return min(score, 25.0)


def _compute_signal_score(
    df: pd.DataFrame,
    indicators: dict,
    analysis: dict,
) -> Tuple[float, Dict[str, float]]:
    """
    Compute overall signal quality score (0–100) and component breakdown.

    Returns
    -------
    (total_score, components_dict)
    """
    action = analysis.get("action", "hold")
    side = "long" if action == "enter_long" else "short"

    trend    = _score_trend_strength(indicators, side)
    vol_fit  = _score_volatility(df, indicators)
    volume   = _score_volume(df)
    momentum = _score_momentum(indicators, side)

    total = trend + vol_fit + volume + momentum
    components = {
        "trend_strength": trend,
        "volatility_fit": vol_fit,
        "volume_confirm": volume,
        "momentum_align": momentum,
        "total": total,
    }
    return total, components


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class WinRateMaximizer:
    """
    Three-layer trade gate that maximises win rate by cutting bad trades,
    enforcing risk caps, and maintaining profit consistency.
    """

    def __init__(
        self,
        *,
        max_daily_loss_usd: float = DEFAULT_MAX_DAILY_LOSS_USD,
        max_daily_loss_pct: float = DEFAULT_MAX_DAILY_LOSS_PCT,
        max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
        max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
        signal_threshold: float = DEFAULT_SIGNAL_THRESHOLD,
        win_rate_window: int = DEFAULT_WIN_RATE_WINDOW,
        min_win_rate: float = DEFAULT_MIN_WIN_RATE,
        symbol_window: int = DEFAULT_SYMBOL_WINDOW,
        min_symbol_win_rate: float = DEFAULT_MIN_SYMBOL_WIN_RATE,
    ) -> None:
        # --- Layer 1: Risk Caps ---
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_drawdown_pct = max_drawdown_pct

        # --- Layer 2: Signal Quality ---
        self.signal_threshold = signal_threshold

        # --- Layer 3: Profit Consistency ---
        self.win_rate_window = win_rate_window
        self.min_win_rate = min_win_rate
        self.symbol_window = symbol_window
        self.min_symbol_win_rate = min_symbol_win_rate

        # --- Session State ---
        self._lock = threading.Lock()
        self._total_trades: int = 0
        self._wins: int = 0
        self._daily_pnl: float = 0.0
        self._consecutive_losses: int = 0
        self._session_start_balance: float = 0.0
        self._peak_balance: float = 0.0
        self._current_balance: float = 0.0
        self._session_halted: bool = False
        self._halt_reason: str = ""

        # Rolling outcome window (True = win, False = loss)
        self._outcome_window: Deque[bool] = deque(maxlen=win_rate_window)

        # Per-symbol rolling win rate
        self._symbol_outcomes: Dict[str, Deque[bool]] = {}

        # Session date (to reset daily state on new day)
        self._session_date: Optional[str] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger.info(
            "✅ WinRateMaximizer initialised | "
            "risk_cap=daily$%.0f/%.0f%% | signal_min=%.0f | win_rate_floor=%.0f%%",
            max_daily_loss_usd,
            max_daily_loss_pct * 100,
            signal_threshold,
            min_win_rate * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def approve_trade(
        self,
        symbol: str,
        analysis: dict,
        df: pd.DataFrame,
        indicators: dict,
        account_balance: float = 0.0,
    ) -> Tuple[bool, str, float]:
        """
        Evaluate whether a trade should be executed.

        Parameters
        ----------
        symbol:          Trading pair, e.g. "BTC-USD".
        analysis:        Strategy analysis dict (must contain "action" key).
        df:              OHLCV DataFrame for the symbol.
        indicators:      Dict of indicator Series (rsi_9/14, adx, ema_9/21/50,
                         macd_hist, atr).
        account_balance: Current account balance in USD (used for % loss cap).

        Returns
        -------
        (approved, reason, score)
            approved  – True if the trade passes all three layers.
            reason    – Human-readable explanation.
            score     – Signal quality score (0–100).
        """
        with self._lock:
            self._maybe_reset_day()
            self._sync_balance(account_balance)

            action = analysis.get("action", "hold")
            if action not in ("enter_long", "enter_short"):
                return True, "Non-entry action — pass-through", 0.0

            # ── Layer 1: Risk Caps ────────────────────────────────────────
            halted, halt_msg = self._check_risk_caps(account_balance)
            if halted:
                return False, halt_msg, 0.0

            # ── Layer 2: Signal Quality Score ─────────────────────────────
            score, components = _compute_signal_score(df, indicators, analysis)
            score_summary = (
                f"trend={components['trend_strength']:.0f} "
                f"vol={components['volatility_fit']:.0f} "
                f"volume={components['volume_confirm']:.0f} "
                f"mom={components['momentum_align']:.0f} "
                f"→ total={score:.1f}"
            )
            if score < self.signal_threshold:
                reason = (
                    f"Signal score {score:.1f} < threshold {self.signal_threshold:.0f} "
                    f"[{score_summary}]"
                )
                logger.info("   🚫 WinRateMaximizer (signal quality): %s", reason)
                return False, reason, score

            # ── Layer 3: Profit Consistency Gate ──────────────────────────
            consistency_ok, consistency_msg = self._check_consistency(symbol)
            if not consistency_ok:
                logger.info("   🚫 WinRateMaximizer (consistency): %s", consistency_msg)
                return False, consistency_msg, score

            logger.info(
                "   ✅ WinRateMaximizer APPROVED %s | score=%.1f [%s]",
                symbol,
                score,
                score_summary,
            )
            return True, f"Approved | score={score:.1f}", score

    def record_outcome(
        self,
        symbol: str,
        is_win: bool,
        pnl_usd: float,
    ) -> None:
        """
        Record the outcome of a completed trade.

        Must be called after every closed position so that risk caps and
        profit consistency metrics stay current.
        """
        with self._lock:
            self._total_trades += 1
            self._daily_pnl += pnl_usd
            self._current_balance += pnl_usd

            if is_win:
                self._wins += 1
                self._consecutive_losses = 0
                # Update peak
                if self._current_balance > self._peak_balance:
                    self._peak_balance = self._current_balance
            else:
                self._consecutive_losses += 1

            # Rolling outcome windows
            self._outcome_window.append(is_win)

            sym_deque = self._symbol_outcomes.setdefault(
                symbol, deque(maxlen=self.symbol_window)
            )
            sym_deque.append(is_win)

            # Check if session should be halted after this loss
            if not is_win:
                if self._consecutive_losses >= self.max_consecutive_losses:
                    self._session_halted = True
                    self._halt_reason = (
                        f"{self._consecutive_losses} consecutive losses "
                        f"(cap: {self.max_consecutive_losses})"
                    )
                    logger.warning(
                        "⛔ WinRateMaximizer: Cool-down activated — %s",
                        self._halt_reason,
                    )

                daily_loss = -self._daily_pnl
                if self._session_start_balance > 0:
                    daily_loss_pct = daily_loss / self._session_start_balance
                else:
                    daily_loss_pct = 0.0

                if daily_loss >= self.max_daily_loss_usd or daily_loss_pct >= self.max_daily_loss_pct:
                    self._session_halted = True
                    self._halt_reason = (
                        f"Daily loss cap reached: ${daily_loss:.2f} "
                        f"({daily_loss_pct*100:.1f}%)"
                    )
                    logger.warning(
                        "⛔ WinRateMaximizer: Session halted — %s",
                        self._halt_reason,
                    )

                if self._peak_balance > 0:
                    dd = (self._peak_balance - self._current_balance) / self._peak_balance
                    if dd >= self.max_drawdown_pct:
                        self._session_halted = True
                        self._halt_reason = (
                            f"Max drawdown reached: {dd*100:.1f}% "
                            f"(cap: {self.max_drawdown_pct*100:.0f}%)"
                        )
                        logger.warning(
                            "⛔ WinRateMaximizer: Session halted — %s",
                            self._halt_reason,
                        )

            win_rate = self._wins / self._total_trades if self._total_trades else 0.0
            logger.info(
                "   📊 WinRateMaximizer outcome: %s %s pnl=$%.2f | "
                "session win_rate=%.0f%% (%d/%d) | consec_losses=%d | daily_pnl=$%.2f",
                symbol,
                "WIN" if is_win else "LOSS",
                pnl_usd,
                win_rate * 100,
                self._wins,
                self._total_trades,
                self._consecutive_losses,
                self._daily_pnl,
            )

    def reset_session(self, starting_balance: float = 0.0) -> None:
        """
        Manually reset the daily session state (e.g. at start of each trading day).
        """
        with self._lock:
            self._daily_pnl = 0.0
            self._consecutive_losses = 0
            self._session_halted = False
            self._halt_reason = ""
            if starting_balance > 0:
                self._session_start_balance = starting_balance
                self._current_balance = starting_balance
                self._peak_balance = starting_balance
            self._session_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.info(
                "🔄 WinRateMaximizer session reset | balance=$%.2f",
                self._session_start_balance,
            )

    def get_dashboard(self) -> dict:
        """Return a snapshot of the current state for display/logging."""
        with self._lock:
            win_rate = self._wins / self._total_trades if self._total_trades else 0.0
            rolling_wr = (
                sum(self._outcome_window) / len(self._outcome_window)
                if self._outcome_window
                else 0.0
            )
            dd = 0.0
            if self._peak_balance > 0:
                dd = max(0.0, (self._peak_balance - self._current_balance) / self._peak_balance)

            return {
                "total_trades": self._total_trades,
                "wins": self._wins,
                "losses": self._total_trades - self._wins,
                "win_rate_session": round(win_rate, 4),
                "win_rate_rolling": round(rolling_wr, 4),
                "daily_pnl_usd": round(self._daily_pnl, 2),
                "consecutive_losses": self._consecutive_losses,
                "drawdown_pct": round(dd, 4),
                "session_halted": self._session_halted,
                "halt_reason": self._halt_reason,
                "signal_threshold": self.signal_threshold,
                "min_win_rate": self.min_win_rate,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_reset_day(self) -> None:
        """Auto-reset daily state when the calendar date changes."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._session_date != today:
            if self._session_date is not None:
                logger.info("🌅 WinRateMaximizer: new trading day — resetting daily state")
            self._daily_pnl = 0.0
            self._consecutive_losses = 0
            self._session_halted = False
            self._halt_reason = ""
            self._session_date = today

    def _sync_balance(self, account_balance: float) -> None:
        """Initialise peak/current balance when first balance is provided."""
        if account_balance > 0 and self._session_start_balance == 0.0:
            self._session_start_balance = account_balance
            self._current_balance = account_balance
            self._peak_balance = account_balance

    def _check_risk_caps(self, account_balance: float) -> Tuple[bool, str]:
        """
        Layer 1: evaluate all risk caps.

        Returns (halt, reason) — halt=True means reject the trade.
        """
        if self._session_halted:
            return True, f"Session halted: {self._halt_reason}"

        # Daily loss cap (USD)
        daily_loss_usd = -self._daily_pnl
        if daily_loss_usd >= self.max_daily_loss_usd:
            self._session_halted = True
            self._halt_reason = f"Daily loss cap reached: ${daily_loss_usd:.2f} (cap: ${self.max_daily_loss_usd:.0f})"
            return True, self._halt_reason

        # Daily loss cap (%)
        ref_bal = account_balance if account_balance > 0 else self._session_start_balance
        if ref_bal > 0:
            daily_loss_pct = daily_loss_usd / ref_bal
            if daily_loss_pct >= self.max_daily_loss_pct:
                self._session_halted = True
                self._halt_reason = (
                    f"Daily loss % cap reached: {daily_loss_pct*100:.1f}% "
                    f"(cap: {self.max_daily_loss_pct*100:.0f}%)"
                )
                return True, self._halt_reason

        # Consecutive loss cool-down
        if self._consecutive_losses >= self.max_consecutive_losses:
            return True, (
                f"Consecutive loss cool-down: {self._consecutive_losses} losses "
                f"(cap: {self.max_consecutive_losses})"
            )

        # Drawdown
        if self._peak_balance > 0 and self._current_balance > 0:
            dd = (self._peak_balance - self._current_balance) / self._peak_balance
            if dd >= self.max_drawdown_pct:
                self._session_halted = True
                self._halt_reason = (
                    f"Max drawdown cap reached: {dd*100:.1f}% "
                    f"(cap: {self.max_drawdown_pct*100:.0f}%)"
                )
                return True, self._halt_reason

        return False, ""

    def _check_consistency(self, symbol: str) -> Tuple[bool, str]:
        """
        Layer 3: profit consistency gate.

        Returns (pass, reason).
        """
        # Portfolio rolling win-rate floor (only enforced once window is filled)
        if len(self._outcome_window) >= self.win_rate_window:
            rolling_wr = sum(self._outcome_window) / len(self._outcome_window)
            if rolling_wr < self.min_win_rate:
                return False, (
                    f"Portfolio win-rate {rolling_wr*100:.0f}% < "
                    f"floor {self.min_win_rate*100:.0f}% "
                    f"(last {self.win_rate_window} trades)"
                )

        # Per-symbol win-rate floor
        sym_deque = self._symbol_outcomes.get(symbol)
        if sym_deque and len(sym_deque) >= self.symbol_window:
            sym_wr = sum(sym_deque) / len(sym_deque)
            if sym_wr < self.min_symbol_win_rate:
                return False, (
                    f"{symbol} win-rate {sym_wr*100:.0f}% < "
                    f"floor {self.min_symbol_win_rate*100:.0f}% "
                    f"(last {self.symbol_window} trades)"
                )

        return True, "ok"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[WinRateMaximizer] = None
_INSTANCE_LOCK = threading.Lock()


def get_win_rate_maximizer(**kwargs: object) -> WinRateMaximizer:
    """
    Return (or create) the process-wide WinRateMaximizer singleton.

    Keyword arguments are forwarded to ``WinRateMaximizer.__init__`` only on
    the **first** call; subsequent calls return the existing instance.
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = WinRateMaximizer(**kwargs)  # type: ignore[arg-type]
    return _INSTANCE
