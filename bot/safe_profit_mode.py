"""
NIJA Safe Profit Mode
======================

Activates a protective "safe profit mode" when a meaningful amount of daily
profit has been locked in.  Once active, the bot stops opening new positions
and focuses entirely on managing and protecting existing ones.

Safe Profit Mode Activation Rules
-----------------------------------
The mode activates when EITHER of these thresholds is crossed (whichever
comes first):

  * Daily profit-to-target ratio  ≥ ``target_pct_threshold``   (default 1.0)
    i.e. today's profit already meets or exceeds the daily target.

  * Locked-profit fraction        ≥ ``lock_fraction_threshold`` (default 0.50)
    i.e. at least 50 % of today's accumulated profit is ratchet-locked.

When active:
  * New position entries are **blocked** (``should_block_entry()`` → ``True``).
  * The bot continues to manage and exit existing positions normally.
  * Status is persisted so it survives bot restarts within the same day.

Usage
-----
    from bot.safe_profit_mode import get_safe_profit_mode

    spm = get_safe_profit_mode()

    # After every trade close (pass updated daily figures):
    spm.update(
        daily_profit_usd=today_pnl,
        daily_target_usd=daily_goal,
        locked_profit_usd=ratchet_locked_amount,
    )

    # Before opening a new position:
    if spm.should_block_entry():
        return {'action': 'hold', 'reason': spm.get_block_reason()}

    # Human-readable dashboard:
    print(spm.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.safe_profit_mode")


# ---------------------------------------------------------------------------
# Mode enum
# ---------------------------------------------------------------------------

class SafeMode(str, Enum):
    """Safe profit mode state."""
    INACTIVE = "inactive"   # Normal trading – new entries allowed
    ACTIVE   = "active"     # Profit locked in – no new entries allowed


# ---------------------------------------------------------------------------
# State dataclass (persisted to disk)
# ---------------------------------------------------------------------------

@dataclass
class SafeProfitState:
    """Snapshot of the current safe-profit-mode state."""
    date: str
    daily_profit_usd: float
    daily_target_usd: float
    locked_profit_usd: float
    lock_fraction: float          # locked_profit_usd / daily_profit_usd  (0–1)
    mode: str                     # SafeMode.value
    activated_at: Optional[str]   # ISO timestamp when mode first activated today
    trades_blocked: int           # entry attempts blocked since activation

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SafeProfitModeManager:
    """
    Daily gate that prevents new position entries once sufficient profit is
    locked in, protecting the day's gains from being given back.

    Thread-safe singleton — obtain via ``get_safe_profit_mode()``.
    """

    DATA_DIR   = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "safe_profit_mode_state.json"

    DEFAULT_TARGET_PCT_THRESHOLD  = 1.0    # activate at 100 % of daily target
    DEFAULT_LOCK_FRACTION_THRESHOLD = 0.50  # activate when 50 % of profit is locked

    def __init__(
        self,
        target_pct_threshold: float = DEFAULT_TARGET_PCT_THRESHOLD,
        lock_fraction_threshold: float = DEFAULT_LOCK_FRACTION_THRESHOLD,
    ) -> None:
        self._lock = threading.Lock()
        self.target_pct_threshold   = target_pct_threshold
        self.lock_fraction_threshold = lock_fraction_threshold

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Runtime state (overwritten by _load_state if today's data exists)
        self._today              = str(date.today())
        self._daily_profit_usd   = 0.0
        self._daily_target_usd   = 0.0
        self._locked_profit_usd  = 0.0
        self._mode               = SafeMode.INACTIVE
        self._activated_at: Optional[str] = None
        self._trades_blocked     = 0

        self._load_state()

        logger.info("=" * 60)
        logger.info("🔒 Safe Profit Mode Manager initialised")
        logger.info("   target_pct_threshold   : %.0f%%", target_pct_threshold * 100)
        logger.info("   lock_fraction_threshold: %.0f%%", lock_fraction_threshold * 100)
        logger.info("   current mode           : %s", self._mode.value.upper())
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        daily_profit_usd: float,
        daily_target_usd: float,
        locked_profit_usd: float,
    ) -> bool:
        """
        Re-evaluate whether safe profit mode should activate.

        Call after every trade close (or balance update) with the latest
        daily figures.

        Args:
            daily_profit_usd:  Net profit earned today (realised).
            daily_target_usd:  Today's profit target in USD.
            locked_profit_usd: Portion of today's profit that is ratchet-locked.

        Returns:
            ``True`` if the mode *just* activated on this call.
        """
        with self._lock:
            today = str(date.today())
            if today != self._today:
                self._reset_for_new_day(today)

            self._daily_profit_usd  = daily_profit_usd
            self._daily_target_usd  = daily_target_usd
            self._locked_profit_usd = locked_profit_usd

            just_activated = self._evaluate_activation()
            self._save_state()
            return just_activated

    def should_block_entry(self) -> bool:
        """
        Return ``True`` when new position entries should be blocked.

        Automatically resets at midnight (new trading day).
        """
        with self._lock:
            today = str(date.today())
            if today != self._today:
                self._reset_for_new_day(today)
                self._save_state()
            return self._mode == SafeMode.ACTIVE

    def record_blocked_attempt(self) -> None:
        """Increment the counter of entry attempts blocked by safe mode."""
        with self._lock:
            self._trades_blocked += 1
            self._save_state()

    def get_block_reason(self) -> str:
        """Human-readable reason why new entries are blocked."""
        with self._lock:
            lock_pct = (
                self._locked_profit_usd / self._daily_profit_usd * 100
                if self._daily_profit_usd > 0 else 0.0
            )
            return (
                f"🔒 Safe Profit Mode ACTIVE – locked ${self._locked_profit_usd:.2f} "
                f"({lock_pct:.0f}% of ${self._daily_profit_usd:.2f} daily profit). "
                f"No new entries until next trading day."
            )

    def is_active(self) -> bool:
        """Return ``True`` when safe profit mode is active (entries blocked)."""
        return self.should_block_entry()

    def get_state(self) -> SafeProfitState:
        """Return a snapshot of the current state."""
        with self._lock:
            lf = (
                self._locked_profit_usd / self._daily_profit_usd
                if self._daily_profit_usd > 0 else 0.0
            )
            return SafeProfitState(
                date=self._today,
                daily_profit_usd=self._daily_profit_usd,
                daily_target_usd=self._daily_target_usd,
                locked_profit_usd=self._locked_profit_usd,
                lock_fraction=round(lf, 4),
                mode=self._mode.value,
                activated_at=self._activated_at,
                trades_blocked=self._trades_blocked,
            )

    def get_report(self) -> str:
        """Return a human-readable status report."""
        s = self.get_state()
        lock_pct = s.lock_fraction * 100
        target_pct = (
            s.daily_profit_usd / s.daily_target_usd * 100
            if s.daily_target_usd > 0 else 0.0
        )
        lines = [
            "",
            "=" * 60,
            "  NIJA SAFE PROFIT MODE STATUS",
            "=" * 60,
            f"  Date             : {s.date}",
            f"  Mode             : {s.mode.upper()}",
            f"  Daily Profit     : ${s.daily_profit_usd:>10,.2f}",
            f"  Daily Target     : ${s.daily_target_usd:>10,.2f}  ({target_pct:.0f}% achieved)",
            f"  Locked Profit    : ${s.locked_profit_usd:>10,.2f}  ({lock_pct:.0f}% of P/L locked)",
            f"  Activated At     : {s.activated_at or 'N/A'}",
            f"  Entries Blocked  : {s.trades_blocked}",
            "=" * 60,
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_activation(self) -> bool:
        """Activate safe profit mode if thresholds are crossed.

        Returns ``True`` if the mode was just activated this call.
        """
        if self._mode == SafeMode.ACTIVE:
            return False  # already active

        if self._daily_profit_usd <= 0:
            return False  # no profit yet

        # Condition 1: daily target reached
        if self._daily_target_usd > 0:
            target_ratio = self._daily_profit_usd / self._daily_target_usd
            if target_ratio >= self.target_pct_threshold:
                self._activate(
                    f"daily target reached ({target_ratio * 100:.0f}% of target)"
                )
                return True

        # Condition 2: sufficient fraction of profit is ratchet-locked
        lock_fraction = (
            self._locked_profit_usd / self._daily_profit_usd
            if self._daily_profit_usd > 0 else 0.0
        )
        if lock_fraction >= self.lock_fraction_threshold:
            self._activate(
                f"lock fraction reached ({lock_fraction * 100:.0f}% of today's P/L locked)"
            )
            return True

        return False

    def _activate(self, reason: str) -> None:
        """Transition to ACTIVE state and log the event."""
        self._mode        = SafeMode.ACTIVE
        self._activated_at = datetime.now().isoformat()
        logger.info("=" * 60)
        logger.info("🔒 SAFE PROFIT MODE ACTIVATED")
        logger.info("   Reason        : %s", reason)
        logger.info(
            "   Daily profit  : $%.2f / $%.2f target",
            self._daily_profit_usd,
            self._daily_target_usd,
        )
        logger.info(
            "   Locked        : $%.2f (%.0f%% of today's P/L)",
            self._locked_profit_usd,
            (self._locked_profit_usd / self._daily_profit_usd * 100)
            if self._daily_profit_usd > 0 else 0,
        )
        logger.info("   New entries BLOCKED for the rest of the trading day.")
        logger.info("=" * 60)

    def _reset_for_new_day(self, today: str) -> None:
        """Reset state at the start of a new trading day."""
        logger.info("📅 Safe Profit Mode: new day (%s) – resetting state.", today)
        self._today             = today
        self._daily_profit_usd  = 0.0
        self._daily_target_usd  = 0.0
        self._locked_profit_usd = 0.0
        self._mode              = SafeMode.INACTIVE
        self._activated_at      = None
        self._trades_blocked    = 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            data = {
                "date":              self._today,
                "daily_profit_usd":  self._daily_profit_usd,
                "daily_target_usd":  self._daily_target_usd,
                "locked_profit_usd": self._locked_profit_usd,
                "mode":              self._mode.value,
                "activated_at":      self._activated_at,
                "trades_blocked":    self._trades_blocked,
            }
            with open(self.STATE_FILE, "w") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save safe profit mode state: %s", exc)

    def _load_state(self) -> None:
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as fh:
                data = json.load(fh)
            saved_date = data.get("date", "")
            today = str(date.today())
            if saved_date != today:
                logger.info(
                    "📅 Safe Profit Mode: stale state (%s) – starting fresh.",
                    saved_date,
                )
                return  # Keep defaults (INACTIVE)

            self._today             = today
            self._daily_profit_usd  = data.get("daily_profit_usd",  0.0)
            self._daily_target_usd  = data.get("daily_target_usd",  0.0)
            self._locked_profit_usd = data.get("locked_profit_usd", 0.0)
            self._mode              = SafeMode(data.get("mode", SafeMode.INACTIVE.value))
            self._activated_at      = data.get("activated_at")
            self._trades_blocked    = data.get("trades_blocked", 0)
            logger.info(
                "✅ Safe profit mode state loaded (mode=%s)", self._mode.value
            )
        except Exception as exc:
            logger.warning("Failed to load safe profit mode state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_spm_instance: Optional[SafeProfitModeManager] = None
_spm_lock = threading.Lock()


def get_safe_profit_mode(
    target_pct_threshold: float  = SafeProfitModeManager.DEFAULT_TARGET_PCT_THRESHOLD,
    lock_fraction_threshold: float = SafeProfitModeManager.DEFAULT_LOCK_FRACTION_THRESHOLD,
) -> SafeProfitModeManager:
    """
    Return the global ``SafeProfitModeManager`` singleton.

    Thread-safe; creates one instance on first call.
    """
    global _spm_instance
    if _spm_instance is None:
        with _spm_lock:
            if _spm_instance is None:
                _spm_instance = SafeProfitModeManager(
                    target_pct_threshold=target_pct_threshold,
                    lock_fraction_threshold=lock_fraction_threshold,
                )
    return _spm_instance
