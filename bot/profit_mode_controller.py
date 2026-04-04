"""
Profit Mode Controller
======================

Three-level system that tunes trade frequency and entry aggressiveness so
the bot executes 2–5 trades per hour across all market conditions.

Levels
------
Level 0 — Normal        Standard quality filters; no overrides (same as pre-existing defaults)
Level 1 — Safe Boost    Dynamic batch sizing + idle boost; faster idle scan; existing behaviour
Level 2 — Semi-Aggressive Lower score floor + higher pass rate; 3–5 trades/hour in most markets
Level 3 — Aggressive    Forced micro trades; fallback to top-volume symbol if no candidates pass

Configuration
-------------
Set via environment variable ``NIJA_PROFIT_MODE`` (integer 0–3, default **2**).

Runtime override::

    from bot.profit_mode_controller import get_profit_mode_controller
    get_profit_mode_controller().level = 2   # switch to semi-aggressive

Dynamic adjustments
-------------------
Three automatic mode-shifting systems layer on top of the base level:

1. **PnL-aware mode switching** (env ``NIJA_PNL_MODE_SWITCHING=1`` to enable, default on)
   * ``NIJA_LOSING_STREAK_THRESHOLD`` consecutive losses → drop to Mode 1 (default 3)
   * ``NIJA_WINNING_STREAK_THRESHOLD`` consecutive wins  → bump to Mode 2/3 (default 3)
   * Call ``record_trade_outcome(is_win)`` after each closed trade.

2. **Time-based aggression** (env ``NIJA_TIME_MODE_SWITCHING=1`` to enable, default on)
   * Quiet crypto hours 00–07 UTC → Mode 3 (force activity in thin markets)
   * High-volume US session 13–21 UTC → cap at Mode 2 (stay selective)
   * Other hours → base level unchanged.

3. **Per-account mode** (applied by ``get_effective_level(account_type)``)
   * Platform accounts → floor raised to Mode 2
   * User accounts     → ceiling capped at Mode 1 (safer scaling)

Use ``get_effective_level(account_type)`` to retrieve the fully-composed mode
for a given execution context.

Integration Points
------------------
* **nija_ai_engine.py** — applies ``min_score_absolute`` + scan intervals to
  ``NijaAIEngine`` and ``CycleSpeedController`` on startup.
* **nija_core_loop.py** — overrides effective floor, streak thresholds, and
  enables the top-volume fallback (Level 3) in ``_phase3_scan_and_enter``.
* **profit_optimizer.py** — overrides ``pass_percentile`` in
  ``TradeRankingEngine.should_enter``.
* **trading_strategy.py** — calls ``record_trade_outcome`` inside
  ``record_trade_with_advanced_manager`` so PnL-aware switching stays current.

Author: NIJA Trading Systems
"""

from __future__ import annotations

import datetime
import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("nija.profit_mode_ctrl")


# ---------------------------------------------------------------------------
# Per-level parameter set
# ---------------------------------------------------------------------------

@dataclass
class ProfitModeParams:
    """Complete tunable parameter set for one profit mode level."""

    level: int
    name: str

    # ── nija_ai_engine.py ──────────────────────────────────────────────────
    # NijaAIEngine._score_floor — hard absolute entry floor (composite 0-100)
    min_score_absolute: float
    # CycleSpeedController intervals (seconds)
    interval_fast: int
    interval_normal: int
    interval_slow: int

    # ── nija_core_loop.py ──────────────────────────────────────────────────
    # Consecutive zero-signal cycles before progressive relaxation activates
    forced_entry_streak_threshold: int
    # Consecutive zero-signal cycles before quality floor is fully bypassed
    hard_bypass_streak_threshold: int
    # Effective MIN_SCORE_HARD_FLOOR used inside _phase3_scan_and_enter
    min_score_hard_floor: float
    # Level 3+: fall back to highest-volume scanned symbol when candidates = 0
    enable_volume_fallback: bool

    # ── profit_optimizer.py ────────────────────────────────────────────────
    # TradeRankingEngine percentile gate; lower value = more setups pass
    # 0.55 → top 45% pass | 0.40 → top 60% pass | 0.25 → top 75% pass
    pass_percentile: float


# ---------------------------------------------------------------------------
# Level definitions
# ---------------------------------------------------------------------------

_LEVELS: dict[int, ProfitModeParams] = {
    0: ProfitModeParams(
        level=0,
        name="normal",
        # ── nija_ai_engine
        min_score_absolute=15.5,
        interval_fast=90,
        interval_normal=150,
        interval_slow=300,
        # ── nija_core_loop
        forced_entry_streak_threshold=8,
        hard_bypass_streak_threshold=40,
        min_score_hard_floor=20.0,
        enable_volume_fallback=False,
        # ── profit_optimizer
        pass_percentile=0.55,
    ),
    1: ProfitModeParams(
        level=1,
        name="safe_boost",
        # Faster idle scan; no threshold changes — preserves existing quality bar.
        # Achieves 1–2 trades/hour by scanning more often and boosting idle gaps.
        min_score_absolute=15.5,
        interval_fast=90,
        interval_normal=120,   # slightly faster than normal (was 150s)
        interval_slow=150,     # no more 5-minute cold pauses (was 300s)
        forced_entry_streak_threshold=5,   # relaxation kicks in sooner (was 8)
        hard_bypass_streak_threshold=25,   # hard bypass sooner (was 40)
        min_score_hard_floor=18.0,
        enable_volume_fallback=False,
        pass_percentile=0.55,
    ),
    2: ProfitModeParams(
        level=2,
        name="semi_aggressive",
        # Lower score requirements + higher pass rate → 3–5 trades/hour.
        min_score_absolute=12.0,           # was 15.5 (-22%)
        interval_fast=90,
        interval_normal=120,
        interval_slow=90,                  # never slow — always fast-or-normal
        forced_entry_streak_threshold=3,   # relaxation after ~6 min (was 8→20 min)
        hard_bypass_streak_threshold=15,   # hard bypass after ~30 min (was 40)
        min_score_hard_floor=14.0,         # was 20.0
        enable_volume_fallback=False,
        pass_percentile=0.40,              # top 60% pass (was top 45%)
    ),
    3: ProfitModeParams(
        level=3,
        name="aggressive",
        # Force controlled micro trades — 5+ trades/hour; quality still limited.
        min_score_absolute=8.0,            # accepts very weak setups
        interval_fast=60,                  # scan every 60s when hot
        interval_normal=90,                # normal scan every 90s
        interval_slow=60,                  # never slow — floor at 60s
        forced_entry_streak_threshold=2,   # relaxation after 2 idle cycles
        hard_bypass_streak_threshold=8,    # hard bypass after ~12 min
        min_score_hard_floor=8.0,          # near-zero floor
        enable_volume_fallback=True,       # pick top-volume symbol when no candidates
        pass_percentile=0.25,              # top 75% pass the ranker gate
    ),
}


# ---------------------------------------------------------------------------
# Controller class
# ---------------------------------------------------------------------------

class ProfitModeController:
    """
    Singleton controller that exposes per-level tuning parameters to the AI
    engine, core loop, and profit optimizer.

    Thread-safe; level can be changed at runtime without restarting.
    """

    # ------------------------------------------------------------------
    # PnL-aware switching thresholds (overridable via env vars)
    # ------------------------------------------------------------------
    _LOSING_STREAK_THRESHOLD: int = int(os.getenv("NIJA_LOSING_STREAK_THRESHOLD", "3"))
    _WINNING_STREAK_THRESHOLD: int = int(os.getenv("NIJA_WINNING_STREAK_THRESHOLD", "3"))
    _PNL_MODE_SWITCHING: bool = os.getenv("NIJA_PNL_MODE_SWITCHING", "1") not in ("0", "false", "off")
    _TIME_MODE_SWITCHING: bool = os.getenv("NIJA_TIME_MODE_SWITCHING", "1") not in ("0", "false", "off")

    # UTC hour ranges for time-based mode adjustments
    # Quiet crypto hours  → force Mode 3 (aggressive) to find trades in thin markets
    _QUIET_HOUR_START: int = 0
    _QUIET_HOUR_END: int = 7
    # US-session high-vol hours → cap at Mode 2 to stay selective
    _HIGH_VOL_HOUR_START: int = 13
    _HIGH_VOL_HOUR_END: int = 21

    def __init__(self) -> None:
        raw = os.getenv("NIJA_PROFIT_MODE", "2")
        try:
            lvl = int(raw)
        except ValueError:
            lvl = 2
        lvl = max(0, min(3, lvl))   # clamp to [0, 3]

        self._base_level: int = lvl   # original env setting — never auto-changed
        self._level: int = lvl        # working level — auto-adjusted by PnL streak
        self._lock = threading.Lock()

        # PnL streak counters (positive = consecutive wins, negative = consecutive losses)
        self._loss_streak: int = 0
        self._win_streak: int = 0

        logger.info(
            "💰 ProfitModeController ready — Level %d (%s) | "
            "min_score=%.1f pass_pct=%.2f streak_thresh=%d bypass_thresh=%d | "
            "pnl_switching=%s time_switching=%s",
            lvl,
            _LEVELS[lvl].name,
            _LEVELS[lvl].min_score_absolute,
            _LEVELS[lvl].pass_percentile,
            _LEVELS[lvl].forced_entry_streak_threshold,
            _LEVELS[lvl].hard_bypass_streak_threshold,
            self._PNL_MODE_SWITCHING,
            self._TIME_MODE_SWITCHING,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def level(self) -> int:
        """Current profit mode level (0–3)."""
        with self._lock:
            return self._level

    @level.setter
    def level(self, value: int) -> None:
        """Change the active profit mode level at runtime (thread-safe)."""
        value = max(0, min(3, int(value)))
        with self._lock:
            old = self._level
            self._level = value
        logger.info(
            "💰 ProfitModeController level changed %d (%s) → %d (%s)",
            old, _LEVELS[old].name,
            value, _LEVELS[value].name,
        )

    @property
    def params(self) -> ProfitModeParams:
        """Return the ProfitModeParams for the currently active level."""
        with self._lock:
            return _LEVELS[self._level]

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """True when any profit mode boost is enabled (level ≥ 1)."""
        return self.level >= 1

    def volume_fallback_enabled(self) -> bool:
        """True when Level 3 top-volume fallback is active."""
        return self.params.enable_volume_fallback

    # ------------------------------------------------------------------
    # PnL-aware mode switching
    # ------------------------------------------------------------------

    def record_trade_outcome(self, is_win: bool) -> None:
        """
        Record the result of a closed trade and auto-adjust the working level.

        * ``NIJA_LOSING_STREAK_THRESHOLD`` (default 3) consecutive losses  → drop to Mode 1.
        * ``NIJA_WINNING_STREAK_THRESHOLD`` (default 3) consecutive wins   → bump to Mode 2/3.

        The adjustment is relative to ``_base_level`` (the env-configured level)
        so the bot resets toward its configured baseline when the streak breaks.
        """
        if not self._PNL_MODE_SWITCHING:
            return

        with self._lock:
            if is_win:
                self._win_streak += 1
                self._loss_streak = 0
            else:
                self._loss_streak += 1
                self._win_streak = 0

            win_streak = self._win_streak
            loss_streak = self._loss_streak
            base = self._base_level

        new_level: int
        if loss_streak >= self._LOSING_STREAK_THRESHOLD:
            # Losing streak — drop to Mode 1 (safe boost) floor; never go to 0 (disabled)
            new_level = max(min(base, 1), 1) if base > 0 else 0
        elif win_streak >= self._WINNING_STREAK_THRESHOLD:
            # Winning streak — bump one level above base, capped at Mode 3
            new_level = min(base + 1, 3)
        else:
            # No active streak — restore to base
            new_level = base

        new_level = max(0, min(3, new_level))

        with self._lock:
            old_level = self._level
            self._level = new_level

        if new_level != old_level:
            logger.info(
                "💰 ProfitModeController PnL-switch %d (%s) → %d (%s) "
                "[win_streak=%d loss_streak=%d]",
                old_level, _LEVELS[old_level].name,
                new_level, _LEVELS[new_level].name,
                win_streak, loss_streak,
            )

    # ------------------------------------------------------------------
    # Time-based aggression
    # ------------------------------------------------------------------

    def _time_adjusted_level(self, base: int) -> int:
        """
        Apply time-of-day adjustment to *base* and return the adjusted level.

        * Quiet hours (00–07 UTC) → raise to Mode 3 to force activity in thin markets.
        * High-volume US session (13–21 UTC) → cap at Mode 2 to stay selective.
        * Other hours → return *base* unchanged.
        """
        if not self._TIME_MODE_SWITCHING:
            return base
        hour = datetime.datetime.now(datetime.timezone.utc).hour
        if self._QUIET_HOUR_START <= hour < self._QUIET_HOUR_END:
            adjusted = max(base, 3)
            if adjusted != base:
                logger.debug(
                    "💰 Time-based mode: quiet hours (%02d UTC) → Level %d → %d",
                    hour, base, adjusted,
                )
            return adjusted
        if self._HIGH_VOL_HOUR_START <= hour < self._HIGH_VOL_HOUR_END:
            adjusted = min(base, 2)
            if adjusted != base:
                logger.debug(
                    "💰 Time-based mode: high-vol hours (%02d UTC) → Level %d → %d",
                    hour, base, adjusted,
                )
            return adjusted
        return base

    # ------------------------------------------------------------------
    # Per-account mode
    # ------------------------------------------------------------------

    def get_level_for_account_type(self, account_type) -> int:
        """
        Return the recommended profit mode level for *account_type*.

        * **Platform** accounts → floor raised to Mode 2 (semi-aggressive).
        * **User** accounts     → ceiling capped at Mode 1 (safe boost).
        * Unknown / None        → current working level unchanged.

        This does **not** modify the working level — it only returns the
        recommended level.  Pass the result to ``_LEVELS`` when constructing
        per-account parameters.
        """
        try:
            from broker_manager import AccountType as _AT  # type: ignore
        except ImportError:
            try:
                from bot.broker_manager import AccountType as _AT  # type: ignore
            except ImportError:
                return self.level

        base = self.level
        try:
            if account_type == _AT.USER:
                return min(base, 1)
            if account_type == _AT.PLATFORM:
                return max(base, 2)
        except Exception:
            pass
        return base

    # ------------------------------------------------------------------
    # Composite effective level
    # ------------------------------------------------------------------

    def get_effective_level(self, account_type=None) -> int:
        """
        Return the fully-composed effective profit mode level for the current
        execution context, combining:

        1. Working level (base ± PnL-streak offset)
        2. Time-based adjustment (quiet / high-vol hours)
        3. Per-account-type adjustment (if *account_type* is supplied)

        This is the recommended call-site for any code that needs to act on
        the current profit mode rather than reading ``.level`` directly.
        """
        base = self.level                          # streak-adjusted working level
        timed = self._time_adjusted_level(base)    # time-of-day overlay

        if account_type is not None:
            # Re-apply account-type logic on top of the time-adjusted level
            try:
                from broker_manager import AccountType as _AT  # type: ignore
            except ImportError:
                try:
                    from bot.broker_manager import AccountType as _AT  # type: ignore
                except ImportError:
                    return timed
            try:
                if account_type == _AT.USER:
                    return min(timed, 1)
                if account_type == _AT.PLATFORM:
                    return max(timed, 2)
            except Exception:
                pass

        return timed

    def __repr__(self) -> str:
        p = self.params
        return (
            f"ProfitModeController(level={p.level}, name={p.name!r}, "
            f"min_score={p.min_score_absolute}, pass_pct={p.pass_percentile}, "
            f"streak={p.forced_entry_streak_threshold}, bypass={p.hard_bypass_streak_threshold})"
        )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_controller: Optional[ProfitModeController] = None
_controller_lock = threading.Lock()


def get_profit_mode_controller() -> ProfitModeController:
    """Return (or lazily create) the module-level ProfitModeController singleton."""
    global _controller
    if _controller is None:
        with _controller_lock:
            if _controller is None:
                _controller = ProfitModeController()
    return _controller
