"""
NIJA Portfolio Kill Switch  (v2 -- clean rewrite)

Portfolio-level gate that immediately halts ALL trading activity when
triggered.  Thread-safe singleton with persistent state.

Features
--------
* Manual trigger / reset via code or CLI.
* Auto-trigger on peak-equity drawdown, daily loss, or consecutive losses.
* Propagates to the low-level KillSwitch when available.
* State survives restarts via an atomic JSON write.
* Full audit log of every trigger and reset event.

Author: NIJA Trading Systems
Version: 2.0
Date: March 2026

-- BEGIN CONTENT MARKER --  (everything below this line is the real module)
"""

# ============================================================
# Real module begins here -- the header above is the docstring
# ============================================================

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nija.portfolio_kill_switch")

_MAX_HISTORY_SIZE: int = 100


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class PortfolioKillSwitchConfig:
    """Tunable thresholds for the portfolio kill switch."""

    drawdown_warning_pct: float = 5.0
    drawdown_halt_pct: float = 15.0
    consec_loss_warning: int = 3
    consec_loss_halt: int = 6
    daily_loss_halt_pct: float = 5.0
    auto_trigger_enabled: bool = True
    state_file: str = "data/portfolio_kill_switch_state.json"


# ---------------------------------------------------------------------------
# Trigger record
# ---------------------------------------------------------------------------


@dataclass
class TriggerRecord:
    """Immutable record of a trigger or reset event."""

    event: str
    reason: str
    source: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return {
            "event": self.event,
            "reason": self.reason,
            "source": self.source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class PortfolioKillSwitch:
    """Portfolio-level gate -- single atomic halt for ALL trading.

    Thread-safe singleton; use ``get_portfolio_kill_switch()`` to obtain it.
    """

    def __init__(self, config: Optional[PortfolioKillSwitchConfig] = None) -> None:
        self._cfg = config or PortfolioKillSwitchConfig()
        self._lock = threading.Lock()

        # ---- trigger state ----
        self._triggered: bool = False
        self._trigger_reason: str = ""
        self._trigger_timestamp: Optional[str] = None
        self._history: List[Dict] = []

        # ---- portfolio metrics for auto-trigger ----
        self._peak_equity: Optional[float] = None
        self._current_equity: Optional[float] = None
        self._day_start_equity: Optional[float] = None
        self._day_start_date: Optional[str] = None
        self._consecutive_losses: int = 0

        # ---- state persistence ----
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._state_file = Path(os.path.join(project_root, self._cfg.state_file))
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info(
            "Portfolio halt gate initialised | halt=%.1f%% | consec=%d | auto=%s",
            self._cfg.drawdown_halt_pct,
            self._cfg.consec_loss_halt,
            "ENABLED" if self._cfg.auto_trigger_enabled else "DISABLED",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_triggered(self) -> bool:
        """Return ``True`` if the halt is currently active.

        Also honours the ``NIJA_KILL_SWITCH=1`` environment variable.
        """
        if os.environ.get("NIJA_KILL_SWITCH", "").strip().upper() in (
            "1", "TRUE", "YES"
        ):
            return True
        with self._lock:
            return self._triggered

    def trigger(self, reason: str, source: str = "MANUAL") -> None:
        """Activate the halt gate immediately (idempotent)."""
        with self._lock:
            if self._triggered:
                logger.warning(
                    "Halt gate already active; additional reason: %s", reason
                )
                return
            self._triggered = True
            self._trigger_reason = reason
            self._trigger_timestamp = datetime.now(timezone.utc).isoformat()
            record = TriggerRecord(event="trigger", reason=reason, source=source)
            self._history.append(record.to_dict())

        logger.critical(
            "PORTFOLIO HALT TRIGGERED | reason=%s | source=%s", reason, source
        )
        self._persist_state()
        self._propagate_to_kill_switch(reason, source)

    def reset(self, reason: str = "Manual reset", source: str = "MANUAL") -> None:
        """Deactivate the halt gate."""
        with self._lock:
            if not self._triggered:
                logger.info("Halt gate is already inactive")
                return
            self._triggered = False
            self._trigger_reason = ""
            self._trigger_timestamp = None
            record = TriggerRecord(event="reset", reason=reason, source=source)
            self._history.append(record.to_dict())

        logger.warning(
            "PORTFOLIO HALT RESET | reason=%s | source=%s", reason, source
        )
        self._persist_state()

    def update_equity(self, current_equity: float) -> None:
        """Feed current portfolio equity; fires auto-trigger when limits hit."""
        if not self._cfg.auto_trigger_enabled:
            return

        with self._lock:
            if self._peak_equity is None or current_equity > self._peak_equity:
                self._peak_equity = current_equity
            today = datetime.now(timezone.utc).date().isoformat()
            if self._day_start_date != today:
                self._day_start_equity = current_equity
                self._day_start_date = today
            self._current_equity = current_equity
            peak = self._peak_equity
            day_start = self._day_start_equity

        if peak and peak > 0:
            drawdown_pct = (peak - current_equity) / peak * 100
            if drawdown_pct >= self._cfg.drawdown_halt_pct:
                self.trigger(
                    f"Portfolio drawdown {drawdown_pct:.2f}% >= halt "
                    f"{self._cfg.drawdown_halt_pct:.1f}% "
                    f"(peak ${peak:,.2f} -> now ${current_equity:,.2f})",
                    source="DRAWDOWN_AUTO",
                )
                return
            if drawdown_pct >= self._cfg.drawdown_warning_pct:
                logger.warning(
                    "Portfolio drawdown %.2f%% (warn at %.1f%%)",
                    drawdown_pct, self._cfg.drawdown_warning_pct,
                )

        if day_start and day_start > 0:
            daily_loss_pct = (day_start - current_equity) / day_start * 100
            if daily_loss_pct >= self._cfg.daily_loss_halt_pct:
                self.trigger(
                    f"Daily loss {daily_loss_pct:.2f}% >= halt "
                    f"{self._cfg.daily_loss_halt_pct:.1f}% "
                    f"(day start ${day_start:,.2f} -> now ${current_equity:,.2f})",
                    source="DAILY_LOSS_AUTO",
                )

    def record_trade_result(self, is_winner: bool) -> None:
        """Record a completed trade for consecutive-loss tracking."""
        if not self._cfg.auto_trigger_enabled:
            return

        with self._lock:
            if is_winner:
                self._consecutive_losses = 0
                return
            self._consecutive_losses += 1
            consec = self._consecutive_losses

        logger.warning(
            "Consecutive losses: %d (halt at %d)",
            consec, self._cfg.consec_loss_halt,
        )
        if consec >= self._cfg.consec_loss_halt:
            self.trigger(
                f"Consecutive losses {consec} >= halt threshold "
                f"{self._cfg.consec_loss_halt}",
                source="CONSEC_LOSS_AUTO",
            )
        elif consec >= self._cfg.consec_loss_warning:
            logger.warning(
                "Consecutive losses %d >= warning threshold %d",
                consec, self._cfg.consec_loss_warning,
            )

    def get_status(self) -> Dict:
        """Return a JSON-serialisable status snapshot."""
        with self._lock:
            return {
                "triggered": self._triggered,
                "trigger_reason": self._trigger_reason,
                "trigger_timestamp": self._trigger_timestamp,
                "peak_equity": self._peak_equity,
                "current_equity": self._current_equity,
                "day_start_equity": self._day_start_equity,
                "consecutive_losses": self._consecutive_losses,
                "auto_trigger_enabled": self._cfg.auto_trigger_enabled,
                "recent_history": self._history[-10:],
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _propagate_to_kill_switch(self, reason: str, source: str) -> None:
        """Forward the trigger to the global hard-stop (graceful if absent)."""
        for mod_name in ("bot.kill_switch", "kill_switch"):
            try:
                mod = __import__(mod_name, fromlist=["get_kill_switch"])
                mod.get_kill_switch().activate(
                    f"PortfolioGate: {reason}", source=source
                )
                return
            except Exception:
                pass
        logger.warning("Hard-stop module unavailable -- halt not propagated")

    def _persist_state(self) -> None:
        """Atomically persist state to disk."""
        try:
            with self._lock:
                payload = {
                    "triggered": self._triggered,
                    "trigger_reason": self._trigger_reason,
                    "trigger_timestamp": self._trigger_timestamp,
                    "history": self._history[-_MAX_HISTORY_SIZE:],
                    "last_saved": datetime.now(timezone.utc).isoformat(),
                }
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self._state_file)
        except Exception as exc:
            logger.error("Could not persist halt-gate state: %s", exc)

    def _load_state(self) -> None:
        """Restore persisted state on startup."""
        try:
            if self._state_file.exists():
                payload = json.loads(self._state_file.read_text())
                self._triggered = payload.get("triggered", False)
                self._trigger_reason = payload.get("trigger_reason", "")
                self._trigger_timestamp = payload.get("trigger_timestamp")
                self._history = payload.get("history", [])
                if self._triggered:
                    logger.warning(
                        "Halt gate was active in previous session: %s",
                        self._trigger_reason,
                    )
        except Exception as exc:
            logger.error("Could not load halt-gate state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[PortfolioKillSwitch] = None
_instance_lock = threading.Lock()


def get_portfolio_kill_switch(
    config: Optional[PortfolioKillSwitchConfig] = None,
) -> PortfolioKillSwitch:
    """Return the global singleton ``PortfolioKillSwitch``.

    The first caller may supply a ``PortfolioKillSwitchConfig``; subsequent
    callers receive the same instance regardless of the ``config`` argument.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PortfolioKillSwitch(config)
    return _instance


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    pks = get_portfolio_kill_switch()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "trigger":
        pks.trigger(" ".join(sys.argv[2:]) or "CLI trigger", source="CLI")
    elif cmd == "reset":
        pks.reset(" ".join(sys.argv[2:]) or "CLI reset", source="CLI")
    elif cmd == "status":
        import json as _j
        print(_j.dumps(pks.get_status(), indent=2))
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# LEGACY / COMPAT  (kept so existing imports that reference old names still work)
# ---------------------------------------------------------------------------
# The old file had two merged implementations with enums from implementation-1
# used by other modules.  Re-export stubs so nothing breaks at import time.

try:
    from enum import Enum

    class HaltReason(str, Enum):
        DRAWDOWN = "DRAWDOWN"
        RISK_ENGINE_CORRUPT = "RISK_ENGINE_CORRUPT"
        EXCHANGE_OUTAGE = "EXCHANGE_OUTAGE"
        CAPITAL_MISMATCH = "CAPITAL_MISMATCH"
        MANUAL = "MANUAL"

    class HaltMode(str, Enum):
        NO_NEW_ENTRIES = "NO_NEW_ENTRIES"
        EXIT_ONLY = "EXIT_ONLY"
        FULL_STOP = "FULL_STOP"

except Exception:  # pragma: no cover
    pass

# <<< END OF FILE (all original content below this line has been replaced) >>>
