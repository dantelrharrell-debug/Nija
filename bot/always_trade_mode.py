"""
NIJA Always Trade Mode
======================

Guarantees minimum trade frequency, prevents idle capital, and forces
controlled execution even in low-signal environments.

Three controls
--------------
1. Idle timer  — if no trade has executed in IDLE_TIMEOUT_MINUTES the mode
                 activates and forces the next scan cycle unconditionally.
2. Score floor — when active, the effective MIN_SCORE_HARD_FLOOR is replaced
                 with ATM_FORCED_FLOOR (much lower) so more candidates pass.
3. Size guard  — forced entries always use ATM_FORCED_SIZE_PCT (conservative)
                 so capital is not over-risked on a low-conviction forced entry.

Configuration (environment variables)
--------------------------------------
  NIJA_ATM_IDLE_TIMEOUT_MIN   Minutes without a trade before ATM activates (default: 20)
  NIJA_ATM_FORCED_FLOOR       Score floor override when ATM is active (default: 1.5)
  NIJA_ATM_FORCED_SIZE_PCT    Position size fraction for forced entries (default: 0.25)
  NIJA_ATM_MAX_FORCED_STREAK  Max consecutive forced entries before backoff (default: 3)
  NIJA_ATM_BACKOFF_MIN        Minutes to cool down after max streak (default: 10)
  NIJA_ATM_ENABLED            Set to "0" to disable Always Trade Mode (default: "1")

Usage
-----
    from bot.always_trade_mode import get_always_trade_mode

    atm = get_always_trade_mode()

    # Call once per cycle BEFORE entry logic:
    decision = atm.run_pre_cycle_check(
        user_mode=user_mode,
        open_positions=open_positions_count,
        balance=account_balance,
        last_trade_ts=self.heartbeat_last_trade_time or None,
    )
    if decision.force_entry:
        import bot.nija_core_loop as _ncl
        _ncl.FORCE_NEXT_CYCLE = True

    # Call after every confirmed trade (entry OR exit):
    atm.record_trade(symbol="BTC-USD", trade_type="entry")

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.always_trade_mode")

# ---------------------------------------------------------------------------
# Configuration — all tunable via environment variables
# ---------------------------------------------------------------------------

ATM_IDLE_TIMEOUT_S: float = float(os.environ.get("NIJA_ATM_IDLE_TIMEOUT_MIN", "20")) * 60
ATM_FORCED_FLOOR: float = float(os.environ.get("NIJA_ATM_FORCED_FLOOR", "1.5"))
ATM_FORCED_SIZE_PCT: float = float(os.environ.get("NIJA_ATM_FORCED_SIZE_PCT", "0.25"))
ATM_MAX_FORCED_STREAK: int = int(os.environ.get("NIJA_ATM_MAX_FORCED_STREAK", "3"))
ATM_BACKOFF_S: float = float(os.environ.get("NIJA_ATM_BACKOFF_MIN", "10")) * 60
ATM_ENABLED: bool = os.environ.get("NIJA_ATM_ENABLED", "1").strip() not in ("0", "false", "no")

_STATE_FILE: str = os.environ.get("NIJA_ATM_STATE_FILE", "data/always_trade_state.json")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AlwaysTradeDecision:
    """Result returned by AlwaysTradeMode.run_pre_cycle_check()."""
    force_entry: bool = False
    floor_override: Optional[float] = None   # replaces MIN_SCORE_HARD_FLOOR when set
    size_pct: Optional[float] = None         # position size fraction for forced entries
    reason: str = "ok"
    idle_seconds: float = 0.0
    forced_streak: int = 0


@dataclass
class _State:
    """Persisted state written to NIJA_ATM_STATE_FILE."""
    last_trade_ts: float = field(default_factory=time.time)
    forced_streak: int = 0
    last_forced_ts: float = 0.0
    total_forced_entries: int = 0
    total_trades_recorded: int = 0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AlwaysTradeMode:
    """
    Guarantees minimum trade frequency.

    Records every trade execution and detects when the bot has gone idle for
    longer than ATM_IDLE_TIMEOUT_S.  When idle threshold is exceeded:
      • Sets ``AlwaysTradeDecision.force_entry = True`` — the caller should
        then set ``nija_core_loop.FORCE_NEXT_CYCLE = True``.
      • Returns a lower ``floor_override`` so more candidates pass scoring.
      • Returns a conservative ``size_pct`` so forced trades don't over-risk.

    A forced-entry streak counter limits consecutive forced entries to
    ATM_MAX_FORCED_STREAK before a cooldown (ATM_BACKOFF_S) is applied.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = _State()
        self._load_state()
        if ATM_ENABLED:
            logger.info(
                "✅ Always Trade Mode initialized — idle_timeout=%.0fmin  "
                "forced_floor=%.1f  forced_size=%.0f%%  max_streak=%d",
                ATM_IDLE_TIMEOUT_S / 60,
                ATM_FORCED_FLOOR,
                ATM_FORCED_SIZE_PCT * 100,
                ATM_MAX_FORCED_STREAK,
            )
        else:
            logger.info("⏸️  Always Trade Mode DISABLED (NIJA_ATM_ENABLED=0)")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            p = Path(_STATE_FILE)
            if p.exists():
                with p.open("r") as f:
                    raw = json.load(f)
                valid = {k: v for k, v in raw.items() if k in _State.__dataclass_fields__}
                self._state = _State(**valid)
                logger.debug(
                    "ATM: state loaded — last_trade=%s  streak=%d  total_forced=%d",
                    datetime.fromtimestamp(self._state.last_trade_ts).strftime("%H:%M:%S")
                    if self._state.last_trade_ts else "never",
                    self._state.forced_streak,
                    self._state.total_forced_entries,
                )
        except Exception as exc:
            logger.debug("ATM: state load skipped: %s", exc)

    def _save_state(self) -> None:
        try:
            p = Path(_STATE_FILE)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            with tmp.open("w") as f:
                json.dump(asdict(self._state), f)
            tmp.replace(p)
        except Exception as exc:
            logger.debug("ATM: state save failed: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        symbol: str = "",
        trade_type: str = "entry",
        pnl: float = 0.0,
    ) -> None:
        """
        Reset the idle timer.  Call after every confirmed trade (entry or exit).

        A real entry also resets the forced-streak counter so the bot doesn't
        accumulate a forced streak that triggers backoff after normal trades.
        """
        with self._lock:
            self._state.last_trade_ts = time.time()
            self._state.total_trades_recorded += 1
            if trade_type == "entry":
                self._state.forced_streak = 0
        self._save_state()
        logger.debug(
            "ATM: trade recorded (%s %s pnl=%.4f) — idle timer reset",
            trade_type, symbol, pnl,
        )

    def run_pre_cycle_check(
        self,
        user_mode: bool = False,
        open_positions: int = 0,
        balance: float = 0.0,
        last_trade_ts: Optional[float] = None,
    ) -> AlwaysTradeDecision:
        """
        Evaluate whether a forced entry is warranted this cycle.

        Parameters
        ----------
        user_mode      : If True, entries are already blocked — ATM skips.
        open_positions : Number of currently open positions.
        balance        : Current account balance (USD).
        last_trade_ts  : External last-trade timestamp (e.g. from
                         ``heartbeat_last_trade_time``).  When provided and
                         greater than zero, overrides the internal state so the
                         caller's own trade tracking is respected.

        Returns
        -------
        AlwaysTradeDecision
        """
        if not ATM_ENABLED:
            return AlwaysTradeDecision(reason="ATM disabled")

        with self._lock:
            now = time.time()

            # Use the more-recent of: external reference or internal state.
            ref_ts = self._state.last_trade_ts
            if last_trade_ts and last_trade_ts > 0:
                ref_ts = max(ref_ts, last_trade_ts)

            idle_s = now - ref_ts
            streak = self._state.forced_streak

            # Guard: entries are already blocked externally
            if user_mode:
                return AlwaysTradeDecision(
                    idle_seconds=idle_s,
                    forced_streak=streak,
                    reason="user_mode active — ATM deferred",
                )

            # Guard: below idle threshold
            if idle_s < ATM_IDLE_TIMEOUT_S:
                remaining = ATM_IDLE_TIMEOUT_S - idle_s
                return AlwaysTradeDecision(
                    idle_seconds=idle_s,
                    forced_streak=streak,
                    reason=(
                        f"idle={idle_s:.0f}s  timeout={ATM_IDLE_TIMEOUT_S:.0f}s  "
                        f"activates_in={remaining:.0f}s"
                    ),
                )

            # Guard: streak backoff
            if streak >= ATM_MAX_FORCED_STREAK:
                backoff_elapsed = now - self._state.last_forced_ts
                if backoff_elapsed < ATM_BACKOFF_S:
                    remaining_backoff = ATM_BACKOFF_S - backoff_elapsed
                    return AlwaysTradeDecision(
                        idle_seconds=idle_s,
                        forced_streak=streak,
                        reason=(
                            f"ATM backoff: {streak} consecutive forced entries — "
                            f"cooling down {remaining_backoff:.0f}s more"
                        ),
                    )
                # Backoff expired: reset streak and re-activate
                self._state.forced_streak = 0
                streak = 0

            # --- ATM activates ---
            self._state.forced_streak += 1
            self._state.last_forced_ts = now
            self._state.total_forced_entries += 1
            self._save_state()

            logger.warning(
                "⚡ ALWAYS TRADE MODE ACTIVE — idle=%.0fmin  streak=%d/%d  "
                "floor=%.1f  size=%.0f%%  balance=$%.2f",
                idle_s / 60,
                self._state.forced_streak,
                ATM_MAX_FORCED_STREAK,
                ATM_FORCED_FLOOR,
                ATM_FORCED_SIZE_PCT * 100,
                balance,
            )

            return AlwaysTradeDecision(
                force_entry=True,
                floor_override=ATM_FORCED_FLOOR,
                size_pct=ATM_FORCED_SIZE_PCT,
                reason=(
                    f"idle={idle_s / 60:.1f}min > timeout={ATM_IDLE_TIMEOUT_S / 60:.0f}min  "
                    f"forced_entry=#{self._state.total_forced_entries}"
                ),
                idle_seconds=idle_s,
                forced_streak=self._state.forced_streak,
            )

    def get_status(self) -> dict:
        """Return a summary dict for dashboards or log lines."""
        with self._lock:
            now = time.time()
            idle_s = now - self._state.last_trade_ts
            return {
                "enabled": ATM_ENABLED,
                "idle_seconds": round(idle_s, 1),
                "idle_timeout_seconds": ATM_IDLE_TIMEOUT_S,
                "idle_pct": min(100.0, idle_s / ATM_IDLE_TIMEOUT_S * 100)
                if ATM_IDLE_TIMEOUT_S > 0 else 0.0,
                "is_active": idle_s >= ATM_IDLE_TIMEOUT_S,
                "forced_streak": self._state.forced_streak,
                "max_forced_streak": ATM_MAX_FORCED_STREAK,
                "total_forced_entries": self._state.total_forced_entries,
                "total_trades_recorded": self._state.total_trades_recorded,
                "last_trade_iso": datetime.fromtimestamp(
                    self._state.last_trade_ts
                ).isoformat() if self._state.last_trade_ts else None,
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[AlwaysTradeMode] = None
_singleton_lock = threading.Lock()


def get_always_trade_mode() -> AlwaysTradeMode:
    """Return the global AlwaysTradeMode singleton."""
    global _instance
    with _singleton_lock:
        if _instance is None:
            _instance = AlwaysTradeMode()
        return _instance
