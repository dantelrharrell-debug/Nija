"""
NIJA Pattern Win Tracker
=========================

Tracks per-pattern and per-symbol win rates so the bot can automatically
suppress underperforming setups before they erode the equity curve.

Two safety-first functions are exposed:

pattern_win_tracker(pattern)
    Returns ``True`` (safe to trade) or ``False`` (disable pattern).
    A pattern is only disabled when there is *sufficient evidence* — at least
    **30** recorded trades **and** a win rate below **40 %**.  The higher
    trade minimum (raised from 20 to 30) prevents premature kills when a
    pattern has merely hit a short losing streak.

kill_bad_symbols(symbol) → float
    Returns an exposure multiplier in [0.0, 1.0]:
    * ``0.0``  — symbol is blacklisted (proven loser; skip all entries)
    * ``1.0``  — full exposure (either healthy symbol or *too few trades*)

    **Safety guard**: if fewer than **15** trades have been seen for a symbol
    the function always returns ``1.0``, no matter what the current win rate
    looks like.  This prevents early misjudgement on a handful of unlucky
    trades.

Singleton usage
---------------
::

    from bot.pattern_win_tracker import get_pattern_win_tracker

    tracker = get_pattern_win_tracker()

    # After every closed trade:
    tracker.record(pattern="RSI_OS_BULL", symbol="BTC-USD", is_win=True)

    # Before sizing a new entry:
    if not tracker.pattern_win_tracker("RSI_OS_BULL"):
        return   # pattern disabled — skip

    exposure = tracker.kill_bad_symbols("BTC-USD")
    if exposure == 0.0:
        return   # symbol blacklisted — skip

    position_size *= exposure

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
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

import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, Optional, Tuple

logger = logging.getLogger("nija.pattern_win_tracker")


# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

# Minimum trades required before a *pattern* can be disabled.
# Raised from 20 → 30 to prevent premature kills on short losing streaks.
PATTERN_MIN_TRADES_TO_DISABLE: int = 30

# Win-rate floor for patterns; below this → pattern disabled (if min trades met).
PATTERN_WIN_RATE_FLOOR: float = 0.40

# Rolling window size for pattern statistics.
PATTERN_WINDOW: int = 100

# Minimum trades required before a *symbol* can be penalised or killed.
# Safety guard: < 15 trades → always return full exposure (1.0).
SYMBOL_MIN_TRADES_TO_PENALISE: int = 15

# Win-rate below which a symbol is killed (exposure = 0.0).
SYMBOL_KILL_WIN_RATE: float = 0.35

# Win-rate range for partial exposure reduction [kill_floor, full_floor].
# Between SYMBOL_KILL_WIN_RATE and SYMBOL_FULL_EXPOSURE_WIN_RATE the exposure
# is scaled linearly from 0.0 → 1.0.
SYMBOL_FULL_EXPOSURE_WIN_RATE: float = 0.50

# Rolling window for per-symbol trade outcomes.
SYMBOL_WINDOW: int = 50


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class _Bucket:
    """Rolling outcome counts for a single pattern or symbol."""
    window: Deque[bool] = field(default_factory=deque)   # maxlen set explicitly at construction
    total_recorded: int = 0   # monotonic counter (not capped by window)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    # ------------------------------------------------------------------
    def record(self, is_win: bool) -> None:
        self.window.append(is_win)
        self.total_recorded += 1
        self.last_updated = datetime.utcnow()

    @property
    def trades(self) -> int:
        return self.total_recorded

    @property
    def win_rate(self) -> float:
        if not self.window:
            return 0.0
        return sum(self.window) / len(self.window)

    def to_dict(self) -> dict:
        return {
            "trades": self.trades,
            "win_rate_pct": round(self.win_rate * 100, 1),
            "last_updated": self.last_updated.isoformat(),
        }


# ---------------------------------------------------------------------------
# Core tracker
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
    Thread-safe tracker for both trade patterns and per-symbol outcomes.

    Use :func:`get_pattern_win_tracker` to obtain the process-wide singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._patterns: Dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(window=deque(maxlen=PATTERN_WINDOW))
        )
        self._symbols: Dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(window=deque(maxlen=SYMBOL_WINDOW))
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, pattern: str, symbol: str, is_win: bool) -> None:
        """
        Record the outcome of a closed trade for both the triggering
        *pattern* and the *symbol* traded.

        Parameters
        ----------
        pattern:
            Human-readable pattern label, e.g. ``"RSI_OS_BULL"``.
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        is_win:
            ``True`` if the trade was profitable.
        """
        with self._lock:
            self._patterns[pattern].record(is_win)
            self._symbols[symbol].record(is_win)

        logger.debug(
            "PatternWinTracker.record  pattern=%s symbol=%s win=%s",
            pattern, symbol, is_win,
        )

    # ------------------------------------------------------------------
    # Pattern gate
    # ------------------------------------------------------------------

    def pattern_win_tracker(self, pattern: str) -> bool:
        """
        Determine whether *pattern* is safe to trade.

        Returns
        -------
        bool
            ``True``  — pattern is healthy or has insufficient history.
            ``False`` — pattern is disabled (poor win rate with enough data).

        Logic
        -----
        A pattern is only disabled when **both** conditions hold:

        * ``trades >= PATTERN_MIN_TRADES_TO_DISABLE`` (default **30**) — enough
          evidence; guards against reacting to a short losing streak.
        * ``win_rate < PATTERN_WIN_RATE_FLOOR`` (default **0.40** / 40 %) —
          the pattern is genuinely underperforming.

        The minimum-trade threshold was raised from 20 → 30 as part of the
        safety fix to prevent early misjudgement.
        """
        with self._lock:
            bucket = self._patterns.get(pattern)
            if bucket is None:
                return True   # no data yet → allow

            trades = bucket.trades
            win_rate = bucket.win_rate

        if trades >= PATTERN_MIN_TRADES_TO_DISABLE and win_rate < PATTERN_WIN_RATE_FLOOR:
            logger.warning(
                "PatternWinTracker: pattern '%s' DISABLED "
                "(trades=%d >= %d, win_rate=%.1f%% < %.0f%%)",
                pattern,
                trades,
                PATTERN_MIN_TRADES_TO_DISABLE,
                win_rate * 100,
                PATTERN_WIN_RATE_FLOOR * 100,
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Symbol exposure gate
    # ------------------------------------------------------------------

    def kill_bad_symbols(self, symbol: str) -> float:
        """
        Return the exposure multiplier for *symbol*.

        Returns
        -------
        float
            * ``1.0`` — full exposure (healthy, or **too few trades** to judge).
            * ``0.0`` — blacklisted (proven poor performer; skip all entries).
            * A value in ``(0.0, 1.0)`` — partial exposure for borderline symbols.

        Safety guard
        ------------
        If fewer than ``SYMBOL_MIN_TRADES_TO_PENALISE`` trades (default **15**)
        have been recorded for *symbol*, the function **always returns 1.0**
        regardless of the current win rate.  This prevents early misjudgement
        on a handful of unlucky trades at the start of a symbol's history.
        """
        with self._lock:
            bucket = self._symbols.get(symbol)
            if bucket is None:
                return 1.0   # no data → full exposure

            trades = bucket.trades
            win_rate = bucket.win_rate

        # ── Safety guard: too early to judge ──────────────────────────────
        if trades < SYMBOL_MIN_TRADES_TO_PENALISE:
            exposure = 1.0   # Prevents early misjudgement
            logger.debug(
                "PatternWinTracker.kill_bad_symbols: %s trades=%d < %d "
                "→ exposure=1.0 (safety guard)",
                symbol, trades, SYMBOL_MIN_TRADES_TO_PENALISE,
            )
            return exposure

        # ── Kill: win rate is critically low ──────────────────────────────
        if win_rate < SYMBOL_KILL_WIN_RATE:
            logger.warning(
                "PatternWinTracker.kill_bad_symbols: symbol '%s' KILLED "
                "(trades=%d, win_rate=%.1f%% < %.0f%%)",
                symbol,
                trades,
                win_rate * 100,
                SYMBOL_KILL_WIN_RATE * 100,
            )
            return 0.0

        # ── Partial reduction: marginal win rate ──────────────────────────
        if win_rate < SYMBOL_FULL_EXPOSURE_WIN_RATE:
            # Linear interpolation: win_rate ∈ [kill_floor, full_floor] → exposure ∈ [0.0, 1.0]
            span = SYMBOL_FULL_EXPOSURE_WIN_RATE - SYMBOL_KILL_WIN_RATE
            exposure = (win_rate - SYMBOL_KILL_WIN_RATE) / span
            exposure = round(max(0.0, min(1.0, exposure)), 4)
            logger.debug(
                "PatternWinTracker.kill_bad_symbols: %s partial exposure=%.2f "
                "(win_rate=%.1f%%)",
                symbol, exposure, win_rate * 100,
            )
            return exposure

        # ── Full exposure: healthy symbol ──────────────────────────────────
        return 1.0

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    def get_pattern_stats(self, pattern: str) -> Optional[dict]:
        """Return statistics for *pattern*, or ``None`` if unknown."""
        with self._lock:
            bucket = self._patterns.get(pattern)
        return bucket.to_dict() if bucket else None

    def get_symbol_stats(self, symbol: str) -> Optional[dict]:
        """Return statistics for *symbol*, or ``None`` if unknown."""
        with self._lock:
            bucket = self._symbols.get(symbol)
        return bucket.to_dict() if bucket else None

    def get_disabled_patterns(self) -> Dict[str, dict]:
        """Return all patterns currently evaluated as disabled."""
        result: Dict[str, dict] = {}
        with self._lock:
            snapshot: Dict[str, Tuple[int, float]] = {
                p: (b.trades, b.win_rate) for p, b in self._patterns.items()
            }
        for pattern, (trades, win_rate) in snapshot.items():
            if trades >= PATTERN_MIN_TRADES_TO_DISABLE and win_rate < PATTERN_WIN_RATE_FLOOR:
                result[pattern] = {
                    "trades": trades,
                    "win_rate_pct": round(win_rate * 100, 1),
                }
        return result

    def get_killed_symbols(self) -> Dict[str, dict]:
        """Return all symbols currently killed (exposure == 0.0)."""
        result: Dict[str, dict] = {}
        with self._lock:
            snapshot: Dict[str, Tuple[int, float]] = {
                s: (b.trades, b.win_rate) for s, b in self._symbols.items()
            }
        for symbol, (trades, win_rate) in snapshot.items():
            if trades >= SYMBOL_MIN_TRADES_TO_PENALISE and win_rate < SYMBOL_KILL_WIN_RATE:
                result[symbol] = {
                    "trades": trades,
                    "win_rate_pct": round(win_rate * 100, 1),
                }
        return result

    def get_dashboard(self) -> dict:
        """Return a concise summary suitable for logging or an API response."""
        with self._lock:
            n_patterns = len(self._patterns)
            n_symbols = len(self._symbols)

        return {
            "patterns_tracked": n_patterns,
            "symbols_tracked": n_symbols,
            "disabled_patterns": self.get_disabled_patterns(),
            "killed_symbols": self.get_killed_symbols(),
            "pattern_min_trades": PATTERN_MIN_TRADES_TO_DISABLE,
            "pattern_win_rate_floor_pct": PATTERN_WIN_RATE_FLOOR * 100,
            "symbol_min_trades": SYMBOL_MIN_TRADES_TO_PENALISE,
            "symbol_kill_win_rate_pct": SYMBOL_KILL_WIN_RATE * 100,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[PatternWinTracker] = None
_INSTANCE_LOCK = threading.Lock()


def get_pattern_win_tracker() -> PatternWinTracker:
    """
    Return the process-wide :class:`PatternWinTracker` singleton.

    Thread-safe; safe to call from any thread at any time.
    """
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = PatternWinTracker()
            logger.info(
                "✅ PatternWinTracker initialised "
                "(pattern_min_trades=%d, win_rate_floor=%.0f%%, "
                "symbol_min_trades=%d)",
                PATTERN_MIN_TRADES_TO_DISABLE,
                PATTERN_WIN_RATE_FLOOR * 100,
                SYMBOL_MIN_TRADES_TO_PENALISE,
            )
    return _INSTANCE


__all__ = [
    "PatternWinTracker",
    "get_pattern_win_tracker",
    "PATTERN_MIN_TRADES_TO_DISABLE",
    "PATTERN_WIN_RATE_FLOOR",
    "SYMBOL_MIN_TRADES_TO_PENALISE",
    "SYMBOL_KILL_WIN_RATE",
    "SYMBOL_FULL_EXPOSURE_WIN_RATE",
]


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
