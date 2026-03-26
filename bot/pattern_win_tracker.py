"""
NIJA Pattern Win Tracker
=========================
Three integrated features in one module:

1. **Per-pattern win-rate analytics**
   Maintains a rolling window of trade outcomes for each named entry
   pattern (RSI_DIVERGENCE, BB_BREAKOUT, RSI_BB_COMBO, etc.).

2. **Auto-disable losing strategies** (patterns)
   When a pattern's rolling win rate falls below DISABLE_WIN_RATE (40%)
   after at least MIN_TRADES_TO_EVALUATE (20) trades, new entries using
   that pattern are blocked.  The pattern is automatically re-enabled when
   the win rate recovers to REENABLE_WIN_RATE (55%).

3. **Daily profit targeting**
   Tracks realised P&L per calendar day (UTC).  Once DAILY_PROFIT_TARGET_USD
   (default $25, override via env var) is reached, the bot enters slow-down
   mode:
     - position size multiplier drops to 0.50x
     - effective min_score is raised by 0.50
   Daily state resets at midnight UTC.

Usage
-----
    from bot.pattern_win_tracker import get_pattern_win_tracker, Pattern

    pwt = get_pattern_win_tracker()

    # gate on entry
    if not pwt.is_pattern_enabled(Pattern.RSI_DIVERGENCE):
        continue

    if pwt.should_slow_down():
        position_size *= pwt.slow_down_size_multiplier

    # after trade closes
    pwt.record_trade(
        pattern=Pattern.from_reason(analysis.get('reason', '')),
        is_win=is_win,
        pnl_usd=profit_usd,
    )

Persistence
-----------
State is written to ``data/pattern_win_tracker.json`` after every trade
so pattern memory and daily totals survive restarts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Deque, Dict, Optional

logger = logging.getLogger("nija.pattern_win_tracker")

# ---------------------------------------------------------------------------
# Recognised entry patterns
# ---------------------------------------------------------------------------

class Pattern:
    """
    Named entry pattern constants.

    ``from_reason()`` infers the pattern from an analysis reason string so
    no changes are needed in the strategy layer.
    """
    RSI_DIVERGENCE = "RSI_DIVERGENCE"
    BB_BREAKOUT    = "BB_BREAKOUT"
    RSI_BB_COMBO   = "RSI_BB_COMBO"
    MOMENTUM       = "MOMENTUM"
    TREND_FOLLOW   = "TREND_FOLLOW"
    MEAN_REVERT    = "MEAN_REVERT"
    UNKNOWN        = "UNKNOWN"

    ALL = [
        RSI_DIVERGENCE, BB_BREAKOUT, RSI_BB_COMBO,
        MOMENTUM, TREND_FOLLOW, MEAN_REVERT, UNKNOWN,
    ]

    @classmethod
    def from_reason(cls, reason: str) -> str:
        """Infer the pattern from an analysis reason / description string."""
        if not reason:
            return cls.UNKNOWN
        r = reason.upper()
        if "RSI" in r and ("DIV" in r or "DIVERGE" in r):
            return cls.RSI_DIVERGENCE
        if "BB" in r and ("BREAK" in r or "BAND" in r):
            return cls.BB_BREAKOUT
        if "RSI" in r and "BB" in r:
            return cls.RSI_BB_COMBO
        if "MOMENTUM" in r or "MOM" in r:
            return cls.MOMENTUM
        if "TREND" in r:
            return cls.TREND_FOLLOW
        if "REVERT" in r or "MEAN" in r:
            return cls.MEAN_REVERT
        return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROLLING_WINDOW             = 30    # trades per pattern rolling window
MIN_TRADES_TO_EVALUATE     = 20    # gates: must see this many before disabling
DISABLE_WIN_RATE           = 0.40  # below this -> disable pattern
REENABLE_WIN_RATE          = 0.55  # at or above this -> re-enable pattern

SLOWDOWN_SIZE_MULT         = 0.50  # position-size multiplier in slow-down mode
SLOWDOWN_SCORE_BOOST       = 0.50  # added to effective min_score when slowing down

try:
    DAILY_PROFIT_TARGET_USD = float(os.getenv("DAILY_PROFIT_TARGET_USD", "25.0"))
except (ValueError, TypeError):
    DAILY_PROFIT_TARGET_USD = 25.0

_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "pattern_win_tracker.json"
)


# ---------------------------------------------------------------------------
# Internal state helpers
# ---------------------------------------------------------------------------

@dataclass
class _DailyState:
    date_utc:         str   = ""
    daily_profit_usd: float = 0.0
    slow_down_active: bool  = False


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PatternWinTracker:
    """
    Thread-safe pattern win-rate tracker, auto-disable engine, and daily
    profit target guard.
    """

    def __init__(
        self,
        daily_target_usd: float = DAILY_PROFIT_TARGET_USD,
        rolling_window:   int   = ROLLING_WINDOW,
    ) -> None:
        self._lock              = threading.Lock()
        self._daily_target_usd  = daily_target_usd
        self._rolling_window    = rolling_window
        self._windows: Dict[str, Deque[int]] = {
            p: deque(maxlen=rolling_window) for p in Pattern.ALL
        }
        self._disabled: Dict[str, bool] = {p: False for p in Pattern.ALL}
        self._daily = _DailyState()
        self._load()
        logger.info(
            "✅ PatternWinTracker initialised — "
            "daily_target=$%.2f  patterns=%s",
            self._daily_target_usd,
            ", ".join(Pattern.ALL),
        )

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if not os.path.exists(_DATA_PATH):
                return
            with open(_DATA_PATH, encoding="utf-8") as f:
                raw: dict = json.load(f)
            for p, results in raw.get("patterns", {}).items():
                if p in self._windows:
                    self._windows[p] = deque(
                        results[-self._rolling_window:],
                        maxlen=self._rolling_window,
                    )
            for p, disabled in raw.get("disabled", {}).items():
                if p in self._disabled:
                    self._disabled[p] = bool(disabled)
            slow = raw.get("daily", {})
            self._daily = _DailyState(
                date_utc         = slow.get("date_utc", ""),
                daily_profit_usd = float(slow.get("daily_profit_usd", 0.0)),
                slow_down_active = bool(slow.get("slow_down_active", False)),
            )
            logger.info("   PatternWinTracker: state loaded from disk")
        except Exception as exc:
            logger.warning("PatternWinTracker: could not load state: %s", exc)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(_DATA_PATH)), exist_ok=True)
            data = {
                "patterns": {p: list(dq) for p, dq in self._windows.items()},
                "disabled": dict(self._disabled),
                "daily": {
                    "date_utc":         self._daily.date_utc,
                    "daily_profit_usd": self._daily.daily_profit_usd,
                    "slow_down_active": self._daily.slow_down_active,
                },
            }
            with open(_DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("PatternWinTracker: could not save state: %s", exc)

    # ── Daily reset ───────────────────────────────────────────────────────────

    def _maybe_reset_daily(self) -> None:
        """Reset daily P/L accumulator when the UTC date rolls over."""
        today = date.today().isoformat()
        if self._daily.date_utc != today:
            if self._daily.date_utc:
                logger.info(
                    "PatternWinTracker: daily reset (prev=$%.2f, target=$%.2f) -> new day %s",
                    self._daily.daily_profit_usd,
                    self._daily_target_usd,
                    today,
                )
            self._daily = _DailyState(date_utc=today)

    # ── Public API ────────────────────────────────────────────────────────────

    def record_trade(
        self,
        pattern:  str,
        is_win:   bool,
        pnl_usd:  float = 0.0,
    ) -> None:
        """
        Record a closed trade outcome.

        Args:
            pattern:  Pattern constant (or raw reason string -- auto-classified).
            is_win:   True if the trade was profitable.
            pnl_usd:  Realised P&L in USD for daily tracking.
        """
        if pattern not in Pattern.ALL:
            pattern = Pattern.from_reason(pattern)

        with self._lock:
            self._maybe_reset_daily()

            # --- Rolling window update ---
            self._windows[pattern].append(1 if is_win else 0)
            dq = self._windows[pattern]
            n  = len(dq)
            wr = sum(dq) / n if n else 1.0

            # --- Auto-disable / re-enable ---
            if n >= MIN_TRADES_TO_EVALUATE:
                was_disabled = self._disabled[pattern]
                if not was_disabled and wr < DISABLE_WIN_RATE:
                    self._disabled[pattern] = True
                    logger.warning(
                        "PatternWinTracker: AUTO-DISABLED %s "
                        "(win_rate=%.0f%% < %.0f%% after %d trades)",
                        pattern, wr * 100, DISABLE_WIN_RATE * 100, n,
                    )
                elif was_disabled and wr >= REENABLE_WIN_RATE:
                    self._disabled[pattern] = False
                    logger.info(
                        "PatternWinTracker: RE-ENABLED %s "
                        "(win_rate=%.0f%% >= %.0f%%)",
                        pattern, wr * 100, REENABLE_WIN_RATE * 100,
                    )

            # --- Daily profit tracking ---
            self._daily.daily_profit_usd += pnl_usd
            if (
                not self._daily.slow_down_active
                and self._daily.daily_profit_usd >= self._daily_target_usd
            ):
                self._daily.slow_down_active = True
                logger.info(
                    "PatternWinTracker: DAILY TARGET HIT -- "
                    "daily_profit=$%.2f >= target=$%.2f -- slow-down mode ON",
                    self._daily.daily_profit_usd,
                    self._daily_target_usd,
                )

            self._save()

    def is_pattern_enabled(self, pattern: str) -> bool:
        """Return True if new entries using *pattern* are currently allowed."""
        if pattern not in Pattern.ALL:
            pattern = Pattern.from_reason(pattern)
        with self._lock:
            return not self._disabled.get(pattern, False)

    def should_slow_down(self) -> bool:
        """Return True once the daily profit target has been reached."""
        with self._lock:
            self._maybe_reset_daily()
            return self._daily.slow_down_active

    @property
    def slow_down_size_multiplier(self) -> float:
        """Position-size multiplier applied in slow-down mode (0.50x)."""
        return SLOWDOWN_SIZE_MULT

    @property
    def slow_down_score_boost(self) -> float:
        """Added to effective min_score in slow-down mode (+0.50)."""
        return SLOWDOWN_SCORE_BOOST

    def get_daily_profit(self) -> float:
        """Return today's accumulated realised P&L in USD."""
        with self._lock:
            self._maybe_reset_daily()
            return self._daily.daily_profit_usd

    def get_report(self) -> dict:
        """Return a JSON-serialisable snapshot for logging or API endpoints."""
        with self._lock:
            self._maybe_reset_daily()
            stats = []
            for p, dq in self._windows.items():
                n  = len(dq)
                wr = (sum(dq) / n) if n else None
                stats.append({
                    "pattern":      p,
                    "total_trades": n,
                    "win_rate":     round(wr, 3) if wr is not None else None,
                    "disabled":     self._disabled[p],
                })
            return {
                "patterns":          stats,
                "daily_profit_usd":  round(self._daily.daily_profit_usd, 2),
                "daily_target_usd":  self._daily_target_usd,
                "slow_down_active":  self._daily.slow_down_active,
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[PatternWinTracker] = None
_lock = threading.Lock()


def get_pattern_win_tracker(
    daily_target_usd: float = DAILY_PROFIT_TARGET_USD,
) -> PatternWinTracker:
    """Return the process-wide singleton PatternWinTracker."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = PatternWinTracker(daily_target_usd=daily_target_usd)
    return _instance
