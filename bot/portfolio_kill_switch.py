"""
NIJA Portfolio Kill Switch
==========================

Global portfolio-level kill switch that immediately halts ALL trading
activity across all strategies and symbols when triggered.

Features
--------
* Manual trigger via code, CLI, or the ``NIJA_KILL_SWITCH=1`` environment
  variable.
* Auto-trigger on portfolio drawdown from peak equity.
* Auto-trigger on excessive daily loss.
* Auto-trigger on too many consecutive losing trades.
* Propagates to the global ``KillSwitch`` (``bot/kill_switch.py``) so that
  the rest of the system is also aware.
* Thread-safe singleton.
* Persistent state across restarts (atomic JSON write).
* Full audit log of all trigger and reset events.

Usage
-----
::

    from bot.portfolio_kill_switch import get_portfolio_kill_switch

    pks = get_portfolio_kill_switch()

    # Check before every trade entry
    if pks.is_triggered():
        return  # all trading halted

    # Manual panic button
    pks.trigger("Suspicious account activity detected")

    # Update equity so auto-triggers can fire
    pks.update_equity(current_equity=95_000.0)

    # Record trade outcomes for consecutive-loss tracking
    pks.record_trade_result(is_winner=False)

    # After root-cause analysis, re-enable trading
    pks.reset("Root cause resolved — system verified")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_MAX_HISTORY_SIZE: int = 100   # maximum trigger/reset records persisted

logger = logging.getLogger("nija.portfolio_kill_switch")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class PortfolioKillSwitchConfig:
    """Tunable thresholds for the portfolio kill switch."""

    # Drawdown from peak equity (%)
    drawdown_warning_pct: float = 5.0    # emit WARNING at this level
    drawdown_halt_pct: float = 15.0      # trigger kill switch at this level

    # Consecutive losing trades
    consec_loss_warning: int = 3         # emit WARNING after this many losses
    consec_loss_halt: int = 6            # trigger kill switch after this many

    # Daily loss from start-of-day equity (%)
    daily_loss_halt_pct: float = 5.0     # trigger kill switch at this level

    # Master auto-trigger flag — set False to disable all auto-triggers
    auto_trigger_enabled: bool = True

    # State persistence path (relative to project root)
    state_file: str = "data/portfolio_kill_switch_state.json"


# ---------------------------------------------------------------------------
# Trigger record
# ---------------------------------------------------------------------------


@dataclass
class TriggerRecord:
    """Immutable record of a kill-switch trigger or reset event."""

    event: str   # "trigger" or "reset"
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
# Core portfolio kill switch
# ---------------------------------------------------------------------------


class PortfolioKillSwitch:
    """
    Portfolio-level kill switch — single atomic gate for ALL trading.

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

        # ---- state file ----
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._state_file = Path(os.path.join(project_root, self._cfg.state_file))
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        self._load_state()

        logger.info("=" * 70)
        logger.info("🛡️  NIJA Portfolio Kill Switch initialised")
        logger.info("=" * 70)
        logger.info("   Drawdown halt     : %.1f%%", self._cfg.drawdown_halt_pct)
        logger.info("   Consec-loss halt  : %d losses", self._cfg.consec_loss_halt)
        logger.info("   Daily loss halt   : %.1f%%", self._cfg.daily_loss_halt_pct)
        logger.info(
            "   Auto-trigger      : %s",
            "ENABLED" if self._cfg.auto_trigger_enabled else "DISABLED",
        )
        logger.info(
            "   Current state     : %s",
            "TRIGGERED 🚨" if self._triggered else "NORMAL ✅",
        )
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_triggered(self) -> bool:
        """Return ``True`` if the kill switch is currently active.

        Also honours the ``NIJA_KILL_SWITCH=1`` environment variable so that
        the switch can be set from outside the process (e.g. Docker / k8s).
        """
        if os.environ.get("NIJA_KILL_SWITCH", "").strip().upper() in ("1", "TRUE", "YES"):
            return True
        with self._lock:
            return self._triggered

    def trigger(self, reason: str, source: str = "MANUAL") -> None:
        """Activate the portfolio kill switch immediately.

        Parameters
        ----------
        reason:
            Human-readable explanation (logged and persisted).
        source:
            Caller identifier (e.g. ``"MANUAL"``, ``"DRAWDOWN_AUTO"``).
        """
        with self._lock:
            if self._triggered:
                logger.warning(
                    "⚠️  Portfolio kill switch already triggered; additional reason: %s", reason
                )
                return
            self._triggered = True
            self._trigger_reason = reason
            self._trigger_timestamp = datetime.now(timezone.utc).isoformat()
            record = TriggerRecord(event="trigger", reason=reason, source=source)
            self._history.append(record.to_dict())

        logger.critical("=" * 80)
        logger.critical("🚨 PORTFOLIO KILL SWITCH TRIGGERED 🚨")
        logger.critical("=" * 80)
        logger.critical("Reason : %s", reason)
        logger.critical("Source : %s", source)
        logger.critical("Time   : %s", self._trigger_timestamp)
        logger.critical("=" * 80)
        logger.critical("ALL PORTFOLIO TRADING HALTED IMMEDIATELY")
        logger.critical("=" * 80)

        self._persist_state()
        self._propagate_to_kill_switch(reason, source)

    def reset(self, reason: str = "Manual reset", source: str = "MANUAL") -> None:
        """Deactivate the portfolio kill switch.

        .. warning::
            Only reset after the root cause has been fully investigated and
            resolved.  Manually verify all open positions before resuming
            live trading.
        """
        with self._lock:
            if not self._triggered:
                logger.info("Portfolio kill switch is already inactive")
                return
            self._triggered = False
            self._trigger_reason = ""
            self._trigger_timestamp = None
            record = TriggerRecord(event="reset", reason=reason, source=source)
            self._history.append(record.to_dict())

        logger.warning("=" * 80)
        logger.warning("🟢 PORTFOLIO KILL SWITCH RESET 🟢")
        logger.warning("=" * 80)
        logger.warning("Reason : %s", reason)
        logger.warning("⚠️  Verify all open positions before resuming trading")
        logger.warning("=" * 80)

        self._persist_state()

    def update_equity(self, current_equity: float) -> None:
        """Feed current portfolio equity to the auto-trigger logic.

        Call this on every portfolio valuation (e.g. each scan cycle or
        after each trade closes).

        Parameters
        ----------
        current_equity:
            Current total portfolio value in USD.
        """
        if not self._cfg.auto_trigger_enabled:
            return

        with self._lock:
            # Track peak
            if self._peak_equity is None or current_equity > self._peak_equity:
                self._peak_equity = current_equity

            # Reset daily baseline when the UTC date changes
            today = datetime.now(timezone.utc).date().isoformat()
            if self._day_start_date != today:
                self._day_start_equity = current_equity
                self._day_start_date = today
                logger.debug("📊 Daily equity baseline set: $%.2f", current_equity)

            self._current_equity = current_equity
            peak = self._peak_equity
            day_start = self._day_start_equity

        # Drawdown check (outside lock to avoid holding lock during trigger)
        if peak and peak > 0:
            drawdown_pct = (peak - current_equity) / peak * 100
            if drawdown_pct >= self._cfg.drawdown_halt_pct:
                self.trigger(
                    f"Portfolio drawdown {drawdown_pct:.2f}% ≥ halt threshold "
                    f"{self._cfg.drawdown_halt_pct:.1f}% "
                    f"(peak ${peak:,.2f} → current ${current_equity:,.2f})",
                    source="DRAWDOWN_AUTO",
                )
                return
            if drawdown_pct >= self._cfg.drawdown_warning_pct:
                logger.warning(
                    "⚠️  Portfolio drawdown %.2f%% (warning threshold %.1f%%)",
                    drawdown_pct,
                    self._cfg.drawdown_warning_pct,
                )

        # Daily loss check
        if day_start and day_start > 0:
            daily_loss_pct = (day_start - current_equity) / day_start * 100
            if daily_loss_pct >= self._cfg.daily_loss_halt_pct:
                self.trigger(
                    f"Daily loss {daily_loss_pct:.2f}% ≥ halt threshold "
                    f"{self._cfg.daily_loss_halt_pct:.1f}% "
                    f"(day start ${day_start:,.2f} → current ${current_equity:,.2f})",
                    source="DAILY_LOSS_AUTO",
                )

    def record_trade_result(self, is_winner: bool) -> None:
        """Record a completed trade outcome for consecutive-loss tracking.

        Parameters
        ----------
        is_winner:
            ``True`` if the trade closed with a profit, ``False`` if a loss.
        """
        if not self._cfg.auto_trigger_enabled:
            return

        with self._lock:
            if is_winner:
                if self._consecutive_losses > 0:
                    logger.debug("✅ Win resets consecutive-loss counter (was %d)", self._consecutive_losses)
                self._consecutive_losses = 0
                return
            self._consecutive_losses += 1
            consec = self._consecutive_losses

        logger.warning(
            "📉 Consecutive losses: %d (halt at %d)",
            consec,
            self._cfg.consec_loss_halt,
        )

        if consec >= self._cfg.consec_loss_halt:
            self.trigger(
                f"Consecutive loss limit reached: {consec} losses in a row "
                f"(halt threshold: {self._cfg.consec_loss_halt})",
                source="CONSEC_LOSS_AUTO",
            )
        elif consec >= self._cfg.consec_loss_warning:
            logger.warning(
                "⚠️  Consecutive losses %d ≥ warning threshold %d",
                consec,
                self._cfg.consec_loss_warning,
            )

    def get_status(self) -> Dict:
        """Return a status snapshot for dashboards and health checks."""
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
        """Forward the trigger to the global KillSwitch (graceful if unavailable)."""
        try:
            from bot.kill_switch import get_kill_switch  # type: ignore
            ks = get_kill_switch()
            ks.activate(f"PortfolioKillSwitch: {reason}", source=source)
            return
        except Exception:
            pass
        try:
            from kill_switch import get_kill_switch  # type: ignore
            ks = get_kill_switch()
            ks.activate(f"PortfolioKillSwitch: {reason}", source=source)
        except Exception as exc:
            logger.warning(
                "KillSwitch not available — global halt not propagated: %s", exc
            )

    def _persist_state(self) -> None:
        """Atomically persist trigger state to disk."""
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
            logger.error("❌ Could not persist portfolio kill-switch state: %s", exc)

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
                        "⚠️  Portfolio kill switch was active in previous session: %s",
                        self._trigger_reason,
                    )
        except Exception as exc:
            logger.error("❌ Could not load portfolio kill-switch state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[PortfolioKillSwitch] = None
_instance_lock = threading.Lock()


def get_portfolio_kill_switch(
    config: Optional[PortfolioKillSwitchConfig] = None,
) -> PortfolioKillSwitch:
    """Return the global singleton :class:`PortfolioKillSwitch`.

    The first caller may optionally supply a :class:`PortfolioKillSwitchConfig`
    to customise thresholds.  Subsequent callers receive the same instance
    regardless of the ``config`` argument.
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

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    pks = get_portfolio_kill_switch()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "trigger":
        reason = " ".join(sys.argv[2:]) or "CLI manual trigger"
        pks.trigger(reason, source="CLI")
    elif cmd == "reset":
        reason = " ".join(sys.argv[2:]) or "CLI manual reset"
        pks.reset(reason, source="CLI")
    elif cmd == "status":
        import json as _json
        print(_json.dumps(pks.get_status(), indent=2))
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python portfolio_kill_switch.py [trigger|reset|status] [reason]")
        sys.exit(1)
