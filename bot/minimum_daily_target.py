"""
NIJA Minimum Daily Target System
==================================

Tracks daily profit and LOCKS the bot once the minimum daily target is
reached. This prevents over-trading and locks in profits.

Features
--------
- Configurable daily profit target (USD or % of balance)
- Auto-lock when target is hit (no new entries allowed)
- PIN-protected unlock (owner can resume trading)
- Persistent state (survives restarts)
- Detailed progress reporting for dashboard
- Salary progress integration

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────┐
  │                  MinimumDailyTarget                              │
  │                                                                  │
  │  record_profit(pnl_usd)  →  daily profit accumulates            │
  │  check_and_lock()        →  locks if target hit                  │
  │  is_locked()             →  True when target met                 │
  │  unlock(pin)             →  owner can resume trading             │
  │  get_status()            →  dashboard status dict                │
  └──────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.minimum_daily_target import get_minimum_daily_target

    mdt = get_minimum_daily_target()

    # After each trade:
    mdt.record_profit(pnl_usd=15.0)

    # Before allowing a new entry:
    if mdt.is_locked():
        # Daily goal hit — skip new trade
        ...

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.minimum_daily_target")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DailyTargetConfig:
    """Configuration for the minimum daily target system."""

    # Daily profit target in USD (0 = disabled)
    target_usd: float = 25.0

    # Alternative: target as % of starting balance (0 = use target_usd)
    target_pct: float = 0.0

    # When True, the bot is locked after hitting the daily target
    lock_on_hit: bool = True

    # Owner PIN required to unlock before end of day
    owner_pin: str = os.environ.get("OWNER_PIN", "1234")

    # Auto-unlock at midnight (resets the day)
    auto_unlock_at_midnight: bool = True

    # Whether the system is enabled at all
    enabled: bool = True


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class DailyTargetState:
    """Persisted per-day state."""
    date: str = ""                  # YYYY-MM-DD
    starting_balance: float = 0.0
    current_profit_usd: float = 0.0  # net profit today
    target_usd: float = 25.0
    locked: bool = False
    locked_at: str = ""             # ISO timestamp when locked
    trades_today: int = 0
    winning_trades: int = 0
    unlock_history: list = field(default_factory=list)

    @property
    def progress_pct(self) -> float:
        """Progress toward today's target (0–100+)."""
        if self.target_usd <= 0:
            return 0.0
        return (self.current_profit_usd / self.target_usd) * 100.0

    @property
    def remaining_usd(self) -> float:
        """USD still needed to hit the target."""
        return max(0.0, self.target_usd - self.current_profit_usd)

    @property
    def target_hit(self) -> bool:
        """True once daily profit >= target."""
        return self.current_profit_usd >= self.target_usd


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MinimumDailyTarget:
    """
    Minimum daily target guard: locks new trade entries once the
    owner-configured daily profit goal is reached.
    """

    _DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
    _STATE_FILE_NAME = "minimum_daily_target.json"

    def __init__(
        self,
        config: Optional[DailyTargetConfig] = None,
        data_dir: Optional[str] = None,
    ) -> None:
        self._config = config or DailyTargetConfig()
        data_path = Path(data_dir) if data_dir else self._DEFAULT_DATA_DIR
        data_path.mkdir(parents=True, exist_ok=True)
        self._state_file = data_path / self._STATE_FILE_NAME
        self._lock = threading.Lock()
        self._state = DailyTargetState()
        self._load_state()
        logger.info(
            "🎯 MinimumDailyTarget ready | target=%.2f USD | lock_on_hit=%s",
            self._resolve_target(),
            self._config.lock_on_hit,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_profit(
        self,
        pnl_usd: float,
        is_win: bool = True,
        symbol: str = "",
    ) -> bool:
        """
        Record a closed trade's P&L.

        Returns True if this trade caused the daily target to be hit
        (i.e. the bot just locked itself).
        """
        if not self._config.enabled:
            return False

        with self._lock:
            self._maybe_rollover_day()
            s = self._state
            s.current_profit_usd += pnl_usd
            s.trades_today += 1
            if is_win:
                s.winning_trades += 1
            just_locked = self._check_and_lock()
            self._save_state()
            return just_locked

    def is_locked(self) -> bool:
        """
        Return True if the bot should refuse new entries because the
        daily target has been reached (and lock_on_hit is True).
        """
        if not self._config.enabled:
            return False
        if not self._config.lock_on_hit:
            return False
        with self._lock:
            self._maybe_rollover_day()
            return self._state.locked

    def unlock(self, pin: str = "", reason: str = "Manual override") -> bool:
        """
        Owner can unlock trading before midnight.

        Returns True on success, False if PIN is wrong or system disabled.
        """
        if not self._config.enabled:
            return True  # Nothing to unlock

        expected_pin = self._config.owner_pin
        if expected_pin and pin != expected_pin:
            logger.warning("🔑 Daily-target unlock rejected — wrong PIN")
            return False

        with self._lock:
            self._state.locked = False
            self._state.unlock_history.append(
                {
                    "timestamp": _ts(),
                    "reason": reason,
                }
            )
            self._save_state()
        logger.info("🔓 Daily target lock removed by owner: %s", reason)
        return True

    def set_target(self, target_usd: float, pin: str = "") -> bool:
        """
        Dynamically update the daily target (PIN required if one is set).

        Returns True on success.
        """
        expected_pin = self._config.owner_pin
        if expected_pin and pin != expected_pin:
            logger.warning("🔑 Daily-target set rejected — wrong PIN")
            return False

        with self._lock:
            self._config.target_usd = max(0.0, target_usd)
            self._state.target_usd = self._config.target_usd
            # Re-evaluate lock status
            self._check_and_lock()
            self._save_state()
        logger.info("🎯 Daily target updated → $%.2f", self._config.target_usd)
        return True

    def get_status(self) -> dict:
        """Return a status dict for dashboard display."""
        with self._lock:
            self._maybe_rollover_day()
            s = self._state
            return {
                "enabled": self._config.enabled,
                "date": s.date,
                "target_usd": round(s.target_usd, 2),
                "current_profit_usd": round(s.current_profit_usd, 2),
                "progress_pct": round(s.progress_pct, 1),
                "remaining_usd": round(s.remaining_usd, 2),
                "target_hit": s.target_hit,
                "locked": s.locked,
                "locked_at": s.locked_at,
                "trades_today": s.trades_today,
                "winning_trades": s.winning_trades,
                "win_rate_pct": round(
                    (s.winning_trades / s.trades_today * 100) if s.trades_today else 0,
                    1,
                ),
                "lock_on_hit": self._config.lock_on_hit,
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_target(self) -> float:
        """Return the effective target in USD."""
        if self._config.target_pct > 0 and self._state.starting_balance > 0:
            return self._state.starting_balance * self._config.target_pct
        return self._config.target_usd

    def _check_and_lock(self) -> bool:
        """
        Lock the bot if target is met and lock_on_hit is True.
        Must be called with self._lock held.

        Returns True if the bot was just now locked.
        """
        if not self._config.lock_on_hit:
            return False
        if self._state.locked:
            return False  # Already locked
        if self._state.current_profit_usd >= self._state.target_usd > 0:
            self._state.locked = True
            self._state.locked_at = _ts()
            logger.info(
                "🎯 DAILY TARGET HIT — trading locked! Profit: $%.2f / Target: $%.2f",
                self._state.current_profit_usd,
                self._state.target_usd,
            )
            return True
        return False

    def _maybe_rollover_day(self) -> None:
        """Reset daily state when the calendar date changes (no lock required — caller holds it)."""
        today = str(date.today())
        if self._state.date != today:
            self._rollover_day(today)

    def _rollover_day(self, new_date: str) -> None:
        """Start a fresh day."""
        logger.info(
            "📅 DailyTarget rollover: %s → %s | final profit: $%.2f",
            self._state.date,
            new_date,
            self._state.current_profit_usd,
        )
        self._state = DailyTargetState(
            date=new_date,
            target_usd=self._resolve_target(),
        )
        self._save_state()

    def _save_state(self) -> None:
        try:
            data = {
                "config": {
                    "target_usd": self._config.target_usd,
                    "target_pct": self._config.target_pct,
                    "lock_on_hit": self._config.lock_on_hit,
                    "enabled": self._config.enabled,
                },
                "state": {
                    "date": self._state.date,
                    "starting_balance": self._state.starting_balance,
                    "current_profit_usd": self._state.current_profit_usd,
                    "target_usd": self._state.target_usd,
                    "locked": self._state.locked,
                    "locked_at": self._state.locked_at,
                    "trades_today": self._state.trades_today,
                    "winning_trades": self._state.winning_trades,
                    "unlock_history": self._state.unlock_history,
                },
            }
            tmp = str(self._state_file) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._state_file)
        except Exception as exc:
            logger.error("Failed to persist DailyTarget state: %s", exc)

    def _load_state(self) -> None:
        if not self._state_file.exists():
            self._state.date = str(date.today())
            self._state.target_usd = self._config.target_usd
            return
        try:
            with open(self._state_file) as f:
                data = json.load(f)

            # Restore config overrides from file (allow dynamic updates to persist)
            cfg = data.get("config", {})
            if "target_usd" in cfg:
                self._config.target_usd = cfg["target_usd"]
            if "lock_on_hit" in cfg:
                self._config.lock_on_hit = cfg["lock_on_hit"]
            if "enabled" in cfg:
                self._config.enabled = cfg["enabled"]

            st = data.get("state", {})
            self._state = DailyTargetState(
                date=st.get("date", str(date.today())),
                starting_balance=st.get("starting_balance", 0.0),
                current_profit_usd=st.get("current_profit_usd", 0.0),
                target_usd=st.get("target_usd", self._config.target_usd),
                locked=st.get("locked", False),
                locked_at=st.get("locked_at", ""),
                trades_today=st.get("trades_today", 0),
                winning_trades=st.get("winning_trades", 0),
                unlock_history=st.get("unlock_history", []),
            )
            # Roll over if we're on a new day
            self._maybe_rollover_day()
        except Exception as exc:
            logger.error("Failed to load DailyTarget state: %s", exc)
            self._state.date = str(date.today())
            self._state.target_usd = self._config.target_usd


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[MinimumDailyTarget] = None
_instance_lock = threading.Lock()


def get_minimum_daily_target(
    config: Optional[DailyTargetConfig] = None,
) -> MinimumDailyTarget:
    """Return the process-wide singleton MinimumDailyTarget instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MinimumDailyTarget(config=config)
        return _instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()
