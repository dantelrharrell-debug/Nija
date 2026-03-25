"""
NIJA Stable Profit Mode
=======================

Unified controller that implements the **Stabilize Profit Mode** feature.
It bundles three complementary mechanisms:

1. **Daily Profit Range Lock** — keeps the day's realised P/L inside a
   consistent min/max band.
   * Below the *floor* (``min_daily_profit_usd``): the bot trades normally
     and uses the win-rate tuner to increase frequency if needed.
   * Between floor and *ceiling* (``max_daily_profit_usd``): normal trading
     continues but position sizing is reduced to CONSERVATIVE mode.
   * At or above the *ceiling*: all new entries are **blocked** for the rest
     of the calendar day to lock in the gain and prevent giving it back.

2. **Overtrading Guard** — caps the number of new entries per calendar day
   (``max_daily_trades``) and enforces a minimum time gap between consecutive
   entries (``min_trade_gap_seconds``).  Both limits auto-relax when the
   win rate is strong (≥ ``wr_relax_threshold``) and tighten when it falls
   below the quality floor (``wr_tighten_threshold``).

3. **Win-Rate / Frequency Balance** — reads the current ``FrequencyMode``
   from the existing ``WinRateFrequencyTuner`` singleton and surfaces it in
   every report / decision so operators can see the live balance at a glance.

All three mechanisms share a single JSON state file that survives bot
restarts within the same calendar day.

Usage
-----
::

    from bot.stable_profit_mode import get_stable_profit_mode

    spm = get_stable_profit_mode()

    # ── After every trade close ───────────────────────────────────────
    spm.record_trade(pnl_usd=12.5, is_win=True, daily_profit_usd=47.0)

    # ── Before allowing a new entry ───────────────────────────────────
    decision = spm.can_open_entry()
    if not decision.allowed:
        logger.info("⛔ Stable Profit Mode blocked entry: %s", decision.reason)
        return

    # ── Human-readable dashboard ──────────────────────────────────────
    logger.info(spm.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.stable_profit_mode")


# ---------------------------------------------------------------------------
# Tunable defaults
# ---------------------------------------------------------------------------

# Daily profit range (USD)
DEFAULT_MIN_DAILY_PROFIT_USD: float = 25.0    # floor — stop worrying below this
DEFAULT_MAX_DAILY_PROFIT_USD: float = 150.0   # ceiling — lock gains at or above this

# Overtrading guard
DEFAULT_MAX_DAILY_TRADES: int  = 20   # absolute cap on new entries per day
DEFAULT_MIN_TRADE_GAP_SECS: int = 90  # minimum seconds between consecutive entries

# Win-rate thresholds that adjust the overtrading limits
DEFAULT_WR_RELAX_THRESHOLD:  float = 0.60  # ≥ 60% → relax limits by 25%
DEFAULT_WR_TIGHTEN_THRESHOLD: float = 0.45  # < 45% → tighten limits by 20%


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class StabilityState(str, Enum):
    """High-level stability state of the bot for this calendar day."""
    BUILDING   = "building"      # below min target — trade normally
    ON_TARGET  = "on_target"     # between min and max — be conservative
    LOCKED     = "locked"        # at or above max — block new entries


class EntryVerdict(str, Enum):
    ALLOWED  = "allowed"
    BLOCKED  = "blocked"


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass
class EntryDecision:
    """Result returned by ``can_open_entry()``."""
    verdict: EntryVerdict
    reason: str
    state: str        # StabilityState.value
    daily_profit_usd: float
    trades_today: int

    @property
    def allowed(self) -> bool:
        return self.verdict == EntryVerdict.ALLOWED


@dataclass
class StableProfitSnapshot:
    """Complete state snapshot."""
    date: str
    state: str                    # StabilityState.value
    daily_profit_usd: float
    min_target_usd: float
    max_target_usd: float
    trades_today: int
    max_daily_trades_effective: int
    last_entry_iso: Optional[str]
    entries_blocked_today: int
    win_rate_sample: float        # from rolling window
    freq_mode: str                # FrequencyMode.value or "N/A"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class StableProfitModeController:
    """
    Thread-safe singleton — obtain via ``get_stable_profit_mode()``.
    """

    _DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILENAME    = "stable_profit_mode_state.json"

    def __init__(
        self,
        min_daily_profit_usd: float = DEFAULT_MIN_DAILY_PROFIT_USD,
        max_daily_profit_usd: float = DEFAULT_MAX_DAILY_PROFIT_USD,
        max_daily_trades: int       = DEFAULT_MAX_DAILY_TRADES,
        min_trade_gap_secs: int     = DEFAULT_MIN_TRADE_GAP_SECS,
        wr_relax_threshold: float   = DEFAULT_WR_RELAX_THRESHOLD,
        wr_tighten_threshold: float = DEFAULT_WR_TIGHTEN_THRESHOLD,
    ) -> None:
        self._lock = threading.Lock()

        # Configuration (immutable after construction)
        self._min_target       = min_daily_profit_usd
        self._max_target       = max_daily_profit_usd
        self._base_max_trades  = max_daily_trades
        self._base_gap_secs    = min_trade_gap_secs
        self._wr_relax         = wr_relax_threshold
        self._wr_tighten       = wr_tighten_threshold

        # Data directory — configurable via env variable, falling back to repo default
        _data_env = os.environ.get("NIJA_DATA_DIR")
        self.DATA_DIR  = Path(_data_env) if _data_env else self._DEFAULT_DATA_DIR
        self.STATE_FILE = self.DATA_DIR / self.STATE_FILENAME

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Per-day mutable state
        self._today                    = str(date.today())
        self._daily_profit_usd: float  = 0.0
        self._trades_today: int        = 0
        self._wins_today: int          = 0
        self._last_entry_iso: Optional[str] = None
        self._entries_blocked: int     = 0
        self._state                    = StabilityState.BUILDING

        self._load_state()

        logger.info("=" * 64)
        logger.info("🎯 Stable Profit Mode controller initialised")
        logger.info("   Daily range  : $%.2f – $%.2f", self._min_target, self._max_target)
        logger.info("   Max trades/d : %d  (gap ≥ %ds)", self._base_max_trades, self._base_gap_secs)
        logger.info("   WR relax ≥   : %.0f%%   tighten < %.0f%%",
                    self._wr_relax * 100, self._wr_tighten * 100)
        logger.info("   Current state: %s  profit=$%.2f  trades=%d",
                    self._state.value, self._daily_profit_usd, self._trades_today)
        logger.info("=" * 64)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def can_open_entry(self) -> EntryDecision:
        """
        Decide whether a new position entry is allowed right now.

        Returns an :class:`EntryDecision` with ``.allowed`` and a human-
        readable ``.reason``.
        """
        with self._lock:
            self._maybe_rollover()
            self._refresh_state()

            # 1 — Profit ceiling: lock gains for the rest of the day
            if self._state == StabilityState.LOCKED:
                self._entries_blocked += 1
                self._save_state()
                return EntryDecision(
                    verdict=EntryVerdict.BLOCKED,
                    reason=(
                        f"🔒 Daily profit ceiling reached "
                        f"(${self._daily_profit_usd:.2f} ≥ ${self._max_target:.2f}). "
                        f"No new entries until next trading day."
                    ),
                    state=self._state.value,
                    daily_profit_usd=self._daily_profit_usd,
                    trades_today=self._trades_today,
                )

            # 2 — Overtrading guard: max daily trades (adjusted by win rate)
            eff_max = self._effective_max_trades()
            if self._trades_today >= eff_max:
                self._entries_blocked += 1
                self._save_state()
                return EntryDecision(
                    verdict=EntryVerdict.BLOCKED,
                    reason=(
                        f"🚫 Overtrading guard: reached {self._trades_today}/{eff_max} "
                        f"daily trade cap. No new entries until next trading day."
                    ),
                    state=self._state.value,
                    daily_profit_usd=self._daily_profit_usd,
                    trades_today=self._trades_today,
                )

            # 3 — Minimum time gap between entries
            eff_gap = self._effective_gap_secs()
            if self._last_entry_iso is not None:
                try:
                    last_dt = datetime.fromisoformat(self._last_entry_iso)
                    now_utc = datetime.now(timezone.utc)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    elapsed = (now_utc - last_dt).total_seconds()
                    if elapsed < eff_gap:
                        remaining = int(eff_gap - elapsed)
                        self._entries_blocked += 1
                        self._save_state()
                        return EntryDecision(
                            verdict=EntryVerdict.BLOCKED,
                            reason=(
                                f"⏱️ Min trade gap enforced: last entry {int(elapsed)}s ago "
                                f"(gap={eff_gap}s, {remaining}s remaining). "
                                f"Prevents overtrading flurries."
                            ),
                            state=self._state.value,
                            daily_profit_usd=self._daily_profit_usd,
                            trades_today=self._trades_today,
                        )
                except Exception:
                    pass  # Malformed timestamp — don't block

            # ✅ All checks passed
            return EntryDecision(
                verdict=EntryVerdict.ALLOWED,
                reason="✅ Stable Profit Mode: entry allowed",
                state=self._state.value,
                daily_profit_usd=self._daily_profit_usd,
                trades_today=self._trades_today,
            )

    def record_entry(self) -> None:
        """
        Call when a new position is successfully opened.
        Updates the per-day entry count and records the timestamp.
        """
        with self._lock:
            self._maybe_rollover()
            self._trades_today += 1
            self._last_entry_iso = datetime.now(timezone.utc).isoformat()
            self._save_state()
            logger.debug(
                "🎯 StableProfitMode: entry #%d recorded (daily P/L=$%.2f)",
                self._trades_today, self._daily_profit_usd,
            )

    def record_trade(
        self,
        pnl_usd: float,
        is_win: bool,
        daily_profit_usd: Optional[float] = None,
    ) -> None:
        """
        Call after a position closes.

        Args:
            pnl_usd:           Realised profit/loss of this trade.
            is_win:            Whether the trade was profitable.
            daily_profit_usd:  If provided, overrides the internal running
                               total with the authoritative daily P/L from
                               the broker.  Recommended when available.
        """
        with self._lock:
            self._maybe_rollover()
            if daily_profit_usd is not None:
                self._daily_profit_usd = daily_profit_usd
            else:
                self._daily_profit_usd += pnl_usd
            if is_win:
                self._wins_today += 1
            self._refresh_state()
            self._save_state()
            logger.debug(
                "🎯 StableProfitMode: trade recorded pnl=$%.2f  "
                "daily=$%.2f  state=%s  wins=%d/%d",
                pnl_usd, self._daily_profit_usd,
                self._state.value, self._wins_today, self._trades_today,
            )
            if self._state == StabilityState.LOCKED:
                logger.info(
                    "🔒 STABLE PROFIT MODE: daily ceiling hit "
                    "($%.2f / $%.2f). Entries locked for today.",
                    self._daily_profit_usd, self._max_target,
                )

    def get_state_snapshot(self) -> StableProfitSnapshot:
        """Return a thread-safe snapshot of the current state."""
        with self._lock:
            self._maybe_rollover()
            freq_mode = self._get_freq_mode()
            return StableProfitSnapshot(
                date=self._today,
                state=self._state.value,
                daily_profit_usd=self._daily_profit_usd,
                min_target_usd=self._min_target,
                max_target_usd=self._max_target,
                trades_today=self._trades_today,
                max_daily_trades_effective=self._effective_max_trades(),
                last_entry_iso=self._last_entry_iso,
                entries_blocked_today=self._entries_blocked,
                win_rate_sample=self._win_rate(),
                freq_mode=freq_mode,
            )

    def get_report(self) -> str:
        """Return a human-readable status report suitable for logging."""
        snap = self.get_state_snapshot()
        wr_pct   = snap.win_rate_sample * 100
        profit_progress_pct = (
            snap.daily_profit_usd / snap.max_target_usd * 100
            if snap.max_target_usd > 0 else 0.0
        )
        lines = [
            "",
            "=" * 64,
            "  NIJA STABLE PROFIT MODE — DAILY STATUS",
            "=" * 64,
            f"  Date              : {snap.date}",
            f"  Stability State   : {snap.state.upper()}",
            f"  Daily P/L         : ${snap.daily_profit_usd:>9,.2f}",
            f"  Target Band       : ${snap.min_target_usd:.2f} – ${snap.max_target_usd:.2f}",
            f"  Progress to ceil  : {profit_progress_pct:.0f}%",
            f"  Trades Today      : {snap.trades_today} / {snap.max_daily_trades_effective} (cap)",
            f"  Entries Blocked   : {snap.entries_blocked_today}",
            f"  Win Rate (sample) : {wr_pct:.0f}%",
            f"  Freq Mode         : {snap.freq_mode}",
            "=" * 64,
            "",
        ]
        return "\n".join(lines)

    def is_locked(self) -> bool:
        """Return ``True`` when no new entries should be opened today."""
        decision = self.can_open_entry()
        return not decision.allowed

    def get_daily_profit(self) -> float:
        """Return the accumulated daily realised profit in USD."""
        with self._lock:
            self._maybe_rollover()
            return self._daily_profit_usd

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_state(self) -> None:
        """Update the stability state based on current daily profit."""
        if self._daily_profit_usd >= self._max_target:
            self._state = StabilityState.LOCKED
        elif self._daily_profit_usd >= self._min_target:
            self._state = StabilityState.ON_TARGET
        else:
            self._state = StabilityState.BUILDING

    def _win_rate(self) -> float:
        """Rolling win rate based on today's closed trades."""
        if self._trades_today == 0:
            return 0.0
        return self._wins_today / self._trades_today

    def _effective_max_trades(self) -> int:
        """Max daily trades, adjusted for current win rate."""
        wr = self._win_rate()
        if wr >= self._wr_relax and self._trades_today >= 5:
            # Good win rate — allow 25% more trades
            return int(self._base_max_trades * 1.25)
        if wr < self._wr_tighten and self._trades_today >= 5:
            # Struggling win rate — reduce by 20%
            return max(5, int(self._base_max_trades * 0.80))
        return self._base_max_trades

    def _effective_gap_secs(self) -> int:
        """Minimum entry gap, adjusted for current win rate."""
        wr = self._win_rate()
        if wr >= self._wr_relax and self._trades_today >= 5:
            # Good win rate — allow faster cadence
            return max(30, int(self._base_gap_secs * 0.75))
        if wr < self._wr_tighten and self._trades_today >= 5:
            # Struggling — force longer cool-down
            return int(self._base_gap_secs * 1.50)
        return self._base_gap_secs

    def _get_freq_mode(self) -> str:
        """Return the current FrequencyMode from WinRateFrequencyTuner, or 'N/A'."""
        try:
            from bot.win_rate_frequency_tuner import get_win_rate_frequency_tuner
            params = get_win_rate_frequency_tuner().get_params()
            return params.mode.value
        except Exception:
            try:
                from win_rate_frequency_tuner import get_win_rate_frequency_tuner
                params = get_win_rate_frequency_tuner().get_params()
                return params.mode.value
            except Exception:
                return "N/A"

    def _maybe_rollover(self) -> None:
        """Reset per-day counters at midnight."""
        today = str(date.today())
        if today != self._today:
            logger.info(
                "📅 Stable Profit Mode: new day (%s) — resetting daily state.", today
            )
            self._today               = today
            self._daily_profit_usd    = 0.0
            self._trades_today        = 0
            self._wins_today          = 0
            self._last_entry_iso      = None
            self._entries_blocked     = 0
            self._state               = StabilityState.BUILDING
            self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            payload = {
                "date":              self._today,
                "daily_profit_usd":  self._daily_profit_usd,
                "trades_today":      self._trades_today,
                "wins_today":        self._wins_today,
                "last_entry_iso":    self._last_entry_iso,
                "entries_blocked":   self._entries_blocked,
                "state":             self._state.value,
            }
            with open(self.STATE_FILE, "w") as fh:
                json.dump(payload, fh, indent=2)
        except Exception as exc:
            logger.error("StableProfitMode: failed to save state: %s", exc)

    def _load_state(self) -> None:
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE) as fh:
                data = json.load(fh)
            if data.get("date", "") != self._today:
                logger.info(
                    "📅 Stable Profit Mode: stale state (%s) — starting fresh.",
                    data.get("date", "unknown"),
                )
                return
            self._daily_profit_usd = float(data.get("daily_profit_usd", 0.0))
            self._trades_today     = int(data.get("trades_today", 0))
            self._wins_today       = int(data.get("wins_today", 0))
            self._last_entry_iso   = data.get("last_entry_iso")
            self._entries_blocked  = int(data.get("entries_blocked", 0))
            self._state = StabilityState(
                data.get("state", StabilityState.BUILDING.value)
            )
            logger.info(
                "✅ Stable Profit Mode state loaded — state=%s  "
                "daily=$%.2f  trades=%d",
                self._state.value, self._daily_profit_usd, self._trades_today,
            )
        except Exception as exc:
            logger.warning("StableProfitMode: failed to load state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[StableProfitModeController] = None
_instance_lock = threading.Lock()


def get_stable_profit_mode(
    min_daily_profit_usd: float = DEFAULT_MIN_DAILY_PROFIT_USD,
    max_daily_profit_usd: float = DEFAULT_MAX_DAILY_PROFIT_USD,
    max_daily_trades: int       = DEFAULT_MAX_DAILY_TRADES,
    min_trade_gap_secs: int     = DEFAULT_MIN_TRADE_GAP_SECS,
    wr_relax_threshold: float   = DEFAULT_WR_RELAX_THRESHOLD,
    wr_tighten_threshold: float = DEFAULT_WR_TIGHTEN_THRESHOLD,
) -> StableProfitModeController:
    """
    Return the global :class:`StableProfitModeController` singleton.

    Thread-safe; creates the instance on first call using the supplied
    configuration parameters.  Subsequent calls ignore the parameters and
    return the already-created singleton.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StableProfitModeController(
                    min_daily_profit_usd=min_daily_profit_usd,
                    max_daily_profit_usd=max_daily_profit_usd,
                    max_daily_trades=max_daily_trades,
                    min_trade_gap_secs=min_trade_gap_secs,
                    wr_relax_threshold=wr_relax_threshold,
                    wr_tighten_threshold=wr_tighten_threshold,
                )
    return _instance
