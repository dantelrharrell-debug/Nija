"""
NIJA Global Risk Controller — Kill Switch Brain
================================================

This module is the **single authoritative decision-maker** for whether the NIJA
bot may place any trade.  Every subsystem that wants to enter a position MUST
call ``is_trading_allowed()`` (or ``assert_trading_allowed()``) from this module
before executing an order.

Architecture
------------
::

    ┌───────────────────────────────────────────────────────┐
    │              GlobalRiskController                      │
    │  (Kill-Switch Brain — single source of truth)          │
    │                                                        │
    │  RiskLevel ladder                                      │
    │    GREEN   → normal trading                            │
    │    YELLOW  → caution; position sizes reduced           │
    │    ORANGE  → severe; trading limited to exits only     │
    │    RED     → halt; no new entries, exits only          │
    │    EMERGENCY → full kill switch engaged                │
    │                                                        │
    │  Monitors (checked on every call & in background)      │
    │  ┌────────────────────────────────────────────┐       │
    │  │  KillSwitch        (file + env + manual)   │       │
    │  │  KillSwitchAutoTrigger (daily/weekly loss)  │       │
    │  │  Daily P&L tracker                         │       │
    │  │  Portfolio drawdown tracker                 │       │
    │  │  Consecutive-loss counter                  │       │
    │  │  Consecutive-API-error counter             │       │
    │  │  Balance-delta anomaly detector            │       │
    │  └────────────────────────────────────────────┘       │
    └───────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.global_risk_controller import get_global_risk_controller

    grc = get_global_risk_controller()

    # Gate every trade
    if not grc.is_trading_allowed():
        return

    # Or raise on blocked
    grc.assert_trading_allowed("place_order")

    # Record outcomes so the controller can learn
    grc.record_trade_result(pnl=12.50, is_winner=True)
    grc.record_api_success()
    grc.update_balance(current_balance=1050.0)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.global_risk_controller")

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RiskLevel(Enum):
    """Escalating risk levels for the NIJA trading system.

    Levels are ordered from safest (GREEN) to most severe (EMERGENCY).
    The controller raises the level when risk thresholds are breached and
    lowers it only when conditions improve *and* a cool-down period elapses.
    """
    GREEN = "GREEN"         # All systems go — full trading allowed
    YELLOW = "YELLOW"       # Caution — position sizes automatically reduced
    ORANGE = "ORANGE"       # Elevated risk — exits permitted, new entries limited
    RED = "RED"             # High risk — no new entries; exits & cleanup only
    EMERGENCY = "EMERGENCY" # Kill switch engaged — all operations halted


class RiskAction(Enum):
    """Actions triggered at each risk level."""
    ALLOW_ALL = "ALLOW_ALL"         # GREEN
    REDUCE_SIZE = "REDUCE_SIZE"     # YELLOW — apply position-size multiplier
    EXITS_ONLY = "EXITS_ONLY"       # ORANGE — no new entries
    NO_NEW_ENTRIES = "NO_NEW_ENTRIES"  # RED — alias for EXITS_ONLY
    HALT_ALL = "HALT_ALL"           # EMERGENCY — full stop


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class GlobalRiskConfig:
    """All configurable thresholds for the global risk controller.

    All percentage values are expressed as positive numbers (e.g. ``3.0``
    means 3 %).  Loss thresholds are compared against *negative* P&L.
    """
    # ----- daily loss -------------------------------------------------------
    daily_loss_yellow_pct: float = 1.5   # YELLOW when daily loss ≥ 1.5 %
    daily_loss_orange_pct: float = 2.0   # ORANGE when daily loss ≥ 2.0 %
    daily_loss_red_pct: float = 2.5      # RED when daily loss ≥ 2.5 %
    daily_loss_emergency_pct: float = 3.0  # EMERGENCY (kill switch) at ≥ 3 %

    # ----- portfolio drawdown -----------------------------------------------
    drawdown_yellow_pct: float = 5.0    # YELLOW at 5 % peak-to-trough
    drawdown_orange_pct: float = 10.0   # ORANGE at 10 %
    drawdown_red_pct: float = 15.0      # RED at 15 %
    drawdown_emergency_pct: float = 20.0  # EMERGENCY at 20 %

    # ----- consecutive losses -----------------------------------------------
    consecutive_losses_yellow: int = 2  # YELLOW after 2 losses in a row
    consecutive_losses_orange: int = 3  # ORANGE after 3
    consecutive_losses_red: int = 4     # RED after 4
    consecutive_losses_emergency: int = 5  # EMERGENCY (kill switch) after 5

    # ----- consecutive API errors -------------------------------------------
    api_errors_yellow: int = 3
    api_errors_orange: int = 5
    api_errors_red: int = 7
    api_errors_emergency: int = 10

    # ----- balance anomaly --------------------------------------------------
    balance_delta_emergency_pct: float = 50.0  # EMERGENCY on ≥ 50 % unexplained Δ

    # ----- position-size multipliers ----------------------------------------
    size_multiplier_yellow: float = 0.75   # 75 % of normal size at YELLOW
    size_multiplier_orange: float = 0.50   # 50 % at ORANGE
    size_multiplier_red: float = 0.0       # No new entries at RED

    # ----- background monitor -----------------------------------------------
    monitor_interval_seconds: float = 30.0  # Check risk every 30 s in background
    enable_background_monitor: bool = True

    # ----- cool-down before de-escalating -----------------------------------
    deescalate_cooldown_minutes: float = 15.0  # Must wait 15 min before lowering level


# ---------------------------------------------------------------------------
# Risk event record
# ---------------------------------------------------------------------------

@dataclass
class RiskEvent:
    """Immutable record of a risk-level change."""
    timestamp: str
    from_level: str
    to_level: str
    reason: str
    source: str  # e.g. "DAILY_LOSS", "CONSECUTIVE_LOSSES", "MANUAL", …


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class GlobalRiskController:
    """Kill-switch brain for NIJA.

    Aggregates signals from all risk subsystems and exposes a single,
    thread-safe gate: ``is_trading_allowed()``.

    The controller escalates risk levels automatically when thresholds are
    breached and de-escalates only after conditions improve *and* the
    configured cool-down period has passed.
    """

    def __init__(
        self,
        config: Optional[GlobalRiskConfig] = None,
        base_path: Optional[str] = None,
    ) -> None:
        self._config = config or GlobalRiskConfig()
        self._lock = threading.RLock()

        # Current risk state
        self._level: RiskLevel = RiskLevel.GREEN
        self._level_since: datetime = datetime.utcnow()
        self._event_log: List[RiskEvent] = []

        # Portfolio metrics
        self._peak_balance: Optional[float] = None
        self._current_balance: Optional[float] = None
        self._daily_starting_balance: Optional[float] = None
        self._daily_start_time: Optional[datetime] = None
        self._consecutive_losses: int = 0
        self._consecutive_api_errors: int = 0
        self._total_trades: int = 0
        self._winning_trades: int = 0

        # Manual override flag
        self._manually_halted: bool = False
        self._halt_reason: str = ""

        # Registered callbacks (called on level changes)
        self._on_level_change_callbacks: List[Callable[[RiskLevel, RiskLevel, str], None]] = []

        # Integrate with existing kill_switch module
        self._kill_switch = self._load_kill_switch()
        self._auto_trigger = self._load_auto_trigger()

        # Background monitor thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()
        if self._config.enable_background_monitor:
            self._start_background_monitor()

        logger.info("=" * 70)
        logger.info("🧠 NIJA Global Risk Controller initialized")
        logger.info("=" * 70)
        logger.info(f"   Daily loss EMERGENCY  : {self._config.daily_loss_emergency_pct:.1f}%")
        logger.info(f"   Drawdown EMERGENCY    : {self._config.drawdown_emergency_pct:.1f}%")
        logger.info(f"   Consec. losses EMERG  : {self._config.consecutive_losses_emergency}")
        logger.info(f"   API errors EMERG      : {self._config.api_errors_emergency}")
        logger.info(f"   Background monitor    : {'ENABLED' if self._config.enable_background_monitor else 'DISABLED'}")
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Integration with existing kill_switch module
    # ------------------------------------------------------------------

    def _load_kill_switch(self):
        """Load the singleton KillSwitch (graceful if unavailable)."""
        try:
            from bot.kill_switch import get_kill_switch
            return get_kill_switch()
        except ImportError:
            try:
                from kill_switch import get_kill_switch  # type: ignore
                return get_kill_switch()
            except ImportError:
                logger.warning("⚠️  KillSwitch module not available — file-based kill switch disabled")
                return None

    def _load_auto_trigger(self):
        """Load the singleton KillSwitchAutoTrigger (graceful if unavailable)."""
        try:
            from bot.kill_switch import get_auto_trigger
            return get_auto_trigger(
                max_daily_loss_pct=self._config.daily_loss_emergency_pct,
                max_consecutive_losses=self._config.consecutive_losses_emergency,
                enable_auto_trigger=True,
            )
        except ImportError:
            try:
                from kill_switch import get_auto_trigger  # type: ignore
                return get_auto_trigger(
                    max_daily_loss_pct=self._config.daily_loss_emergency_pct,
                    max_consecutive_losses=self._config.consecutive_losses_emergency,
                    enable_auto_trigger=True,
                )
            except ImportError:
                logger.warning("⚠️  KillSwitchAutoTrigger not available — auto-trigger disabled")
                return None

    # ------------------------------------------------------------------
    # Background monitor
    # ------------------------------------------------------------------

    def _start_background_monitor(self) -> None:
        """Start the background monitoring thread."""
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="GlobalRiskMonitor",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.debug("🔄 Background risk monitor started")

    def _monitor_loop(self) -> None:
        """Periodically re-evaluate risk level even without explicit calls."""
        while not self._stop_monitor.is_set():
            try:
                self._evaluate_risk_level()
            except Exception as exc:
                logger.error(f"❌ Risk monitor loop error: {exc}")
            self._stop_monitor.wait(self._config.monitor_interval_seconds)

    def stop_background_monitor(self) -> None:
        """Stop the background monitoring thread (call on shutdown)."""
        self._stop_monitor.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        logger.debug("🛑 Background risk monitor stopped")

    # ------------------------------------------------------------------
    # Primary gate — called by all trading subsystems
    # ------------------------------------------------------------------

    def is_trading_allowed(self) -> bool:
        """Return ``True`` if new entries are permitted under current risk level.

        This is the **primary gate** that every trade must pass.

        Returns
        -------
        bool
            ``True``  → GREEN or YELLOW (with reduced size)
            ``False`` → ORANGE, RED, or EMERGENCY
        """
        with self._lock:
            # Always sync with the underlying kill switch first
            self._sync_kill_switch()

            if self._manually_halted:
                return False

            return self._level in (RiskLevel.GREEN, RiskLevel.YELLOW)

    def assert_trading_allowed(self, operation: str = "trade") -> None:
        """Raise ``RuntimeError`` if trading is not currently allowed.

        Parameters
        ----------
        operation:
            Human-readable description of the attempted operation (used in
            the exception message and log output).

        Raises
        ------
        RuntimeError
            When the current risk level prohibits new entries.
        """
        if not self.is_trading_allowed():
            msg = (
                f"Cannot perform '{operation}': "
                f"GlobalRiskController level={self._level.value} "
                f"(reason: {self._halt_reason or 'risk threshold exceeded'})"
            )
            logger.error(f"🚨 {msg}")
            raise RuntimeError(msg)

    def is_exits_allowed(self) -> bool:
        """Return ``True`` if exit orders (closing positions) are permitted.

        Exits are always allowed except during a full EMERGENCY stop.
        """
        with self._lock:
            self._sync_kill_switch()
            return self._level != RiskLevel.EMERGENCY

    def get_position_size_multiplier(self) -> float:
        """Return the position-size multiplier for the current risk level.

        Returns
        -------
        float
            1.0  → GREEN (full size)
            0.75 → YELLOW
            0.50 → ORANGE
            0.0  → RED / EMERGENCY (no new entries)
        """
        with self._lock:
            mapping = {
                RiskLevel.GREEN: 1.0,
                RiskLevel.YELLOW: self._config.size_multiplier_yellow,
                RiskLevel.ORANGE: self._config.size_multiplier_orange,
                RiskLevel.RED: self._config.size_multiplier_red,
                RiskLevel.EMERGENCY: 0.0,
            }
            return mapping.get(self._level, 0.0)

    # ------------------------------------------------------------------
    # Manual controls
    # ------------------------------------------------------------------

    def manual_halt(self, reason: str) -> None:
        """Immediately halt all trading (manual override).

        Parameters
        ----------
        reason:
            Human-readable reason — logged and stored in the event history.
        """
        with self._lock:
            self._manually_halted = True
            self._halt_reason = reason
            self._escalate_to(RiskLevel.EMERGENCY, reason, "MANUAL_HALT")
            # Also engage the underlying kill switch
            if self._kill_switch:
                try:
                    self._kill_switch.activate(reason, "GLOBAL_RISK_CONTROLLER")
                except Exception as exc:
                    logger.error(f"❌ Could not activate kill switch: {exc}")

    def manual_resume(self, reason: str = "Manual resume") -> None:
        """Clear the manual halt and attempt to de-escalate.

        The controller will re-evaluate all risk metrics after the halt is
        cleared.  If underlying conditions still warrant a high risk level
        the level will remain elevated.

        Parameters
        ----------
        reason:
            Human-readable reason for resuming.
        """
        with self._lock:
            if not self._manually_halted:
                logger.info("No manual halt active — nothing to resume")
                return
            self._manually_halted = False
            self._halt_reason = ""
            # Deactivate the kill switch if it was engaged by us
            if self._kill_switch and self._kill_switch.is_active():
                try:
                    self._kill_switch.deactivate(reason)
                except Exception as exc:
                    logger.error(f"❌ Could not deactivate kill switch: {exc}")
            logger.warning(f"🟢 Manual halt cleared: {reason}")
            # Re-evaluate to set the correct level
            self._evaluate_risk_level()

    # ------------------------------------------------------------------
    # Metric updates (called by trading engine after each event)
    # ------------------------------------------------------------------

    def update_balance(self, current_balance: float) -> None:
        """Inform the controller of the latest account balance.

        Should be called after every balance fetch from the broker API.
        The controller uses this to track daily P&L and portfolio drawdown.

        Parameters
        ----------
        current_balance:
            Current account balance in USD (or account currency).
        """
        with self._lock:
            # Initialise peak
            if self._peak_balance is None:
                self._peak_balance = current_balance

            # Track new peak
            if current_balance > self._peak_balance:
                self._peak_balance = current_balance

            # Check for unexpected balance delta (possible hack / API issue)
            if self._current_balance is not None and self._current_balance > 0:
                delta_pct = abs(
                    (current_balance - self._current_balance) / self._current_balance * 100
                )
                if delta_pct >= self._config.balance_delta_emergency_pct:
                    reason = (
                        f"Unexpected balance anomaly: {delta_pct:.1f}% change "
                        f"(${self._current_balance:.2f} → ${current_balance:.2f}). "
                        f"Possible unauthorized access or API error."
                    )
                    logger.critical(f"🚨 BALANCE ANOMALY: {reason}")
                    self._escalate_to(RiskLevel.EMERGENCY, reason, "BALANCE_DELTA")

            self._current_balance = current_balance

            # Daily tracking
            if self._should_reset_daily():
                self._daily_starting_balance = current_balance
                self._daily_start_time = datetime.utcnow()
                logger.debug(f"📅 Daily baseline reset: ${current_balance:.2f}")

            # Re-evaluate risk after balance update
            self._evaluate_risk_level()

    def record_trade_result(
        self,
        pnl: float,
        is_winner: bool,
    ) -> None:
        """Record the outcome of a completed trade.

        Parameters
        ----------
        pnl:
            Realised profit/loss of the trade (positive = profit).
        is_winner:
            ``True`` if the trade was profitable, ``False`` otherwise.
        """
        with self._lock:
            self._total_trades += 1
            if is_winner:
                self._consecutive_losses = 0
                self._winning_trades += 1
            else:
                self._consecutive_losses += 1

            logger.debug(
                f"📊 Trade recorded: pnl=${pnl:+.2f} "
                f"win={is_winner} consec_losses={self._consecutive_losses}"
            )

            # Propagate to auto-trigger as well
            if self._auto_trigger:
                try:
                    self._auto_trigger.record_trade_result(is_winner)
                except Exception as exc:
                    logger.debug(f"auto_trigger.record_trade_result error: {exc}")

            self._evaluate_risk_level()

    def record_api_error(self) -> None:
        """Record a consecutive API error.

        Call this every time a broker API call fails.  The counter is
        reset to zero by :meth:`record_api_success`.
        """
        with self._lock:
            self._consecutive_api_errors += 1
            logger.warning(
                f"⚠️  API error #{self._consecutive_api_errors} "
                f"(emergency threshold: {self._config.api_errors_emergency})"
            )
            if self._auto_trigger:
                try:
                    self._auto_trigger.record_api_error()
                except Exception:
                    pass
            self._evaluate_risk_level()

    def record_api_success(self) -> None:
        """Record a successful API call (resets the consecutive error counter)."""
        with self._lock:
            if self._consecutive_api_errors > 0:
                logger.debug(
                    f"✅ API success — resetting error counter "
                    f"(was {self._consecutive_api_errors})"
                )
                self._consecutive_api_errors = 0
            if self._auto_trigger:
                try:
                    self._auto_trigger.record_api_success()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def register_level_change_callback(
        self,
        callback: Callable[[RiskLevel, RiskLevel, str], None],
    ) -> None:
        """Register a function called whenever the risk level changes.

        Parameters
        ----------
        callback:
            Callable with signature ``(old_level, new_level, reason) -> None``.
        """
        with self._lock:
            self._on_level_change_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of the current risk state for dashboards / APIs.

        Returns
        -------
        dict
            Rich dictionary describing the complete risk state.
        """
        with self._lock:
            daily_pnl_pct = self._calc_daily_pnl_pct()
            drawdown_pct = self._calc_drawdown_pct()
            win_rate = (
                self._winning_trades / self._total_trades * 100
                if self._total_trades > 0
                else 0.0
            )
            kill_active = False
            if self._kill_switch:
                try:
                    kill_active = self._kill_switch.is_active()
                except Exception:
                    pass
            return {
                "level": self._level.value,
                "action": self._level_to_action(self._level).value,
                "position_size_multiplier": self.get_position_size_multiplier(),
                "trading_allowed": self._level in (RiskLevel.GREEN, RiskLevel.YELLOW),
                "exits_allowed": self._level != RiskLevel.EMERGENCY,
                "manually_halted": self._manually_halted,
                "halt_reason": self._halt_reason,
                "kill_switch_active": kill_active,
                "metrics": {
                    "current_balance": self._current_balance,
                    "peak_balance": self._peak_balance,
                    "daily_pnl_pct": round(daily_pnl_pct, 3) if daily_pnl_pct is not None else None,
                    "portfolio_drawdown_pct": round(drawdown_pct, 3) if drawdown_pct is not None else None,
                    "consecutive_losses": self._consecutive_losses,
                    "consecutive_api_errors": self._consecutive_api_errors,
                    "total_trades": self._total_trades,
                    "winning_trades": self._winning_trades,
                    "win_rate_pct": round(win_rate, 1),
                },
                "thresholds": {
                    "daily_loss_emergency_pct": self._config.daily_loss_emergency_pct,
                    "drawdown_emergency_pct": self._config.drawdown_emergency_pct,
                    "consecutive_losses_emergency": self._config.consecutive_losses_emergency,
                    "api_errors_emergency": self._config.api_errors_emergency,
                },
                "recent_events": [
                    {
                        "timestamp": e.timestamp,
                        "from": e.from_level,
                        "to": e.to_level,
                        "reason": e.reason,
                        "source": e.source,
                    }
                    for e in self._event_log[-10:]
                ],
                "level_since": self._level_since.isoformat(),
                "timestamp": datetime.utcnow().isoformat(),
            }

    @property
    def current_level(self) -> RiskLevel:
        """Current risk level (read-only)."""
        with self._lock:
            return self._level

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_kill_switch(self) -> None:
        """Synchronise with the underlying ``KillSwitch`` state."""
        if self._kill_switch is None:
            return
        try:
            if self._kill_switch.is_active() and self._level != RiskLevel.EMERGENCY:
                self._escalate_to(
                    RiskLevel.EMERGENCY,
                    "Underlying KillSwitch is active",
                    "KILL_SWITCH_SYNC",
                )
        except Exception as exc:
            logger.debug(f"kill_switch sync error: {exc}")

    def _evaluate_risk_level(self) -> None:
        """Re-compute the appropriate risk level from all current metrics.

        Called automatically whenever a metric is updated and by the
        background monitor thread.  Must be called with ``self._lock`` held
        **or** will acquire it internally.

        The method is idempotent — calling it multiple times with the same
        state is safe.
        """
        if self._manually_halted:
            # Manual halt always wins
            return

        self._sync_kill_switch()

        worst_level = RiskLevel.GREEN
        worst_reason = "All metrics within limits"
        worst_source = "EVALUATE"

        # ---- daily loss check ------------------------------------------
        daily_pnl_pct = self._calc_daily_pnl_pct()
        if daily_pnl_pct is not None and daily_pnl_pct < 0:
            loss = abs(daily_pnl_pct)
            if loss >= self._config.daily_loss_emergency_pct:
                lvl, reason = RiskLevel.EMERGENCY, (
                    f"Daily loss {loss:.2f}% ≥ emergency threshold "
                    f"{self._config.daily_loss_emergency_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DAILY_LOSS"
                )
            elif loss >= self._config.daily_loss_red_pct:
                lvl, reason = RiskLevel.RED, (
                    f"Daily loss {loss:.2f}% ≥ red threshold "
                    f"{self._config.daily_loss_red_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DAILY_LOSS"
                )
            elif loss >= self._config.daily_loss_orange_pct:
                lvl, reason = RiskLevel.ORANGE, (
                    f"Daily loss {loss:.2f}% ≥ orange threshold "
                    f"{self._config.daily_loss_orange_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DAILY_LOSS"
                )
            elif loss >= self._config.daily_loss_yellow_pct:
                lvl, reason = RiskLevel.YELLOW, (
                    f"Daily loss {loss:.2f}% ≥ yellow threshold "
                    f"{self._config.daily_loss_yellow_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DAILY_LOSS"
                )

        # ---- portfolio drawdown check -----------------------------------
        dd_pct = self._calc_drawdown_pct()
        if dd_pct is not None and dd_pct > 0:
            if dd_pct >= self._config.drawdown_emergency_pct:
                lvl, reason = RiskLevel.EMERGENCY, (
                    f"Portfolio drawdown {dd_pct:.2f}% ≥ emergency threshold "
                    f"{self._config.drawdown_emergency_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DRAWDOWN"
                )
            elif dd_pct >= self._config.drawdown_red_pct:
                lvl, reason = RiskLevel.RED, (
                    f"Portfolio drawdown {dd_pct:.2f}% ≥ red threshold "
                    f"{self._config.drawdown_red_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DRAWDOWN"
                )
            elif dd_pct >= self._config.drawdown_orange_pct:
                lvl, reason = RiskLevel.ORANGE, (
                    f"Portfolio drawdown {dd_pct:.2f}% ≥ orange threshold "
                    f"{self._config.drawdown_orange_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DRAWDOWN"
                )
            elif dd_pct >= self._config.drawdown_yellow_pct:
                lvl, reason = RiskLevel.YELLOW, (
                    f"Portfolio drawdown {dd_pct:.2f}% ≥ yellow threshold "
                    f"{self._config.drawdown_yellow_pct:.1f}%"
                )
                worst_level, worst_reason, worst_source = self._max_level(
                    worst_level, worst_reason, worst_source, lvl, reason, "DRAWDOWN"
                )

        # ---- consecutive losses check -----------------------------------
        cl = self._consecutive_losses
        if cl >= self._config.consecutive_losses_emergency:
            lvl, reason = RiskLevel.EMERGENCY, (
                f"{cl} consecutive losses ≥ emergency threshold "
                f"{self._config.consecutive_losses_emergency}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "CONSECUTIVE_LOSSES"
            )
        elif cl >= self._config.consecutive_losses_red:
            lvl, reason = RiskLevel.RED, (
                f"{cl} consecutive losses ≥ red threshold "
                f"{self._config.consecutive_losses_red}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "CONSECUTIVE_LOSSES"
            )
        elif cl >= self._config.consecutive_losses_orange:
            lvl, reason = RiskLevel.ORANGE, (
                f"{cl} consecutive losses ≥ orange threshold "
                f"{self._config.consecutive_losses_orange}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "CONSECUTIVE_LOSSES"
            )
        elif cl >= self._config.consecutive_losses_yellow:
            lvl, reason = RiskLevel.YELLOW, (
                f"{cl} consecutive losses ≥ yellow threshold "
                f"{self._config.consecutive_losses_yellow}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "CONSECUTIVE_LOSSES"
            )

        # ---- consecutive API errors check ------------------------------
        ae = self._consecutive_api_errors
        if ae >= self._config.api_errors_emergency:
            lvl, reason = RiskLevel.EMERGENCY, (
                f"{ae} consecutive API errors ≥ emergency threshold "
                f"{self._config.api_errors_emergency}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "API_ERRORS"
            )
        elif ae >= self._config.api_errors_red:
            lvl, reason = RiskLevel.RED, (
                f"{ae} consecutive API errors ≥ red threshold "
                f"{self._config.api_errors_red}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "API_ERRORS"
            )
        elif ae >= self._config.api_errors_orange:
            lvl, reason = RiskLevel.ORANGE, (
                f"{ae} consecutive API errors ≥ orange threshold "
                f"{self._config.api_errors_orange}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "API_ERRORS"
            )
        elif ae >= self._config.api_errors_yellow:
            lvl, reason = RiskLevel.YELLOW, (
                f"{ae} consecutive API errors ≥ yellow threshold "
                f"{self._config.api_errors_yellow}"
            )
            worst_level, worst_reason, worst_source = self._max_level(
                worst_level, worst_reason, worst_source, lvl, reason, "API_ERRORS"
            )

        # ---- apply the worst level found --------------------------------
        _LEVEL_ORDER = [
            RiskLevel.GREEN,
            RiskLevel.YELLOW,
            RiskLevel.ORANGE,
            RiskLevel.RED,
            RiskLevel.EMERGENCY,
        ]

        if _LEVEL_ORDER.index(worst_level) > _LEVEL_ORDER.index(self._level):
            # Escalate immediately
            self._escalate_to(worst_level, worst_reason, worst_source)
        elif _LEVEL_ORDER.index(worst_level) < _LEVEL_ORDER.index(self._level):
            # De-escalate only after cool-down
            self._try_deescalate(worst_level, worst_reason)

    def _escalate_to(
        self,
        new_level: RiskLevel,
        reason: str,
        source: str,
    ) -> None:
        """Transition to a higher (or equal) risk level immediately."""
        old_level = self._level
        if new_level == old_level:
            return

        event = RiskEvent(
            timestamp=datetime.utcnow().isoformat(),
            from_level=old_level.value,
            to_level=new_level.value,
            reason=reason,
            source=source,
        )
        self._event_log.append(event)
        self._level = new_level
        self._level_since = datetime.utcnow()

        # Prominent logging
        icons = {
            RiskLevel.GREEN: "🟢",
            RiskLevel.YELLOW: "🟡",
            RiskLevel.ORANGE: "🟠",
            RiskLevel.RED: "🔴",
            RiskLevel.EMERGENCY: "🚨",
        }
        icon = icons.get(new_level, "⚠️")
        logger.warning(
            f"{icon} RISK LEVEL: {old_level.value} → {new_level.value} | "
            f"source={source} | {reason}"
        )

        if new_level == RiskLevel.EMERGENCY:
            logger.critical("=" * 70)
            logger.critical("🚨 EMERGENCY STOP — ALL TRADING HALTED")
            logger.critical(f"   Reason: {reason}")
            logger.critical(f"   Source: {source}")
            logger.critical("=" * 70)
            # Engage underlying kill switch
            if self._kill_switch and not self._kill_switch.is_active():
                try:
                    self._kill_switch.activate(reason, f"GLOBAL_RISK_CONTROLLER/{source}")
                except Exception as exc:
                    logger.error(f"❌ Could not activate kill switch: {exc}")

        # Fire callbacks
        for cb in self._on_level_change_callbacks:
            try:
                cb(old_level, new_level, reason)
            except Exception as exc:
                logger.error(f"❌ Level-change callback error: {exc}")

    def _try_deescalate(self, target_level: RiskLevel, reason: str) -> None:
        """Lower the risk level only after the cool-down period has elapsed."""
        cooldown = timedelta(minutes=self._config.deescalate_cooldown_minutes)
        elapsed = datetime.utcnow() - self._level_since

        if elapsed < cooldown:
            remaining = int((cooldown - elapsed).total_seconds())
            logger.debug(
                f"⏳ De-escalation to {target_level.value} pending "
                f"({remaining}s cool-down remaining)"
            )
            return

        old_level = self._level
        event = RiskEvent(
            timestamp=datetime.utcnow().isoformat(),
            from_level=old_level.value,
            to_level=target_level.value,
            reason=reason,
            source="DE_ESCALATION",
        )
        self._event_log.append(event)
        self._level = target_level
        self._level_since = datetime.utcnow()

        logger.info(
            f"🟢 Risk level reduced: {old_level.value} → {target_level.value} | {reason}"
        )

        # Fire callbacks
        for cb in self._on_level_change_callbacks:
            try:
                cb(old_level, target_level, reason)
            except Exception as exc:
                logger.error(f"❌ Level-change callback error: {exc}")

    # ------------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------------

    def _should_reset_daily(self) -> bool:
        """Return True if the daily tracking window should be reset."""
        if self._daily_start_time is None:
            return True
        return datetime.utcnow().date() > self._daily_start_time.date()

    def _calc_daily_pnl_pct(self) -> Optional[float]:
        """Calculate today's P&L as a percentage of the starting balance."""
        if (
            self._current_balance is None
            or self._daily_starting_balance is None
            or self._daily_starting_balance <= 0
        ):
            return None
        return (
            (self._current_balance - self._daily_starting_balance)
            / self._daily_starting_balance
            * 100
        )

    def _calc_drawdown_pct(self) -> Optional[float]:
        """Calculate peak-to-trough portfolio drawdown percentage."""
        if (
            self._peak_balance is None
            or self._current_balance is None
            or self._peak_balance <= 0
        ):
            return None
        dd = (self._peak_balance - self._current_balance) / self._peak_balance * 100
        return max(0.0, dd)

    @staticmethod
    def _level_to_action(level: RiskLevel) -> RiskAction:
        mapping = {
            RiskLevel.GREEN: RiskAction.ALLOW_ALL,
            RiskLevel.YELLOW: RiskAction.REDUCE_SIZE,
            RiskLevel.ORANGE: RiskAction.EXITS_ONLY,
            RiskLevel.RED: RiskAction.NO_NEW_ENTRIES,
            RiskLevel.EMERGENCY: RiskAction.HALT_ALL,
        }
        return mapping.get(level, RiskAction.HALT_ALL)

    @staticmethod
    def _max_level(
        current_worst: RiskLevel,
        current_reason: str,
        current_source: str,
        candidate: RiskLevel,
        candidate_reason: str,
        candidate_source: str,
    ) -> Tuple[RiskLevel, str, str]:
        """Return whichever level is more severe, with its reason and source."""
        _ORDER = [
            RiskLevel.GREEN,
            RiskLevel.YELLOW,
            RiskLevel.ORANGE,
            RiskLevel.RED,
            RiskLevel.EMERGENCY,
        ]
        if _ORDER.index(candidate) > _ORDER.index(current_worst):
            return candidate, candidate_reason, candidate_source
        return current_worst, current_reason, current_source


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_controller: Optional[GlobalRiskController] = None
_controller_lock = threading.Lock()


def get_global_risk_controller(
    config: Optional[GlobalRiskConfig] = None,
) -> GlobalRiskController:
    """Return the process-wide singleton :class:`GlobalRiskController`.

    On the first call the instance is created with the supplied *config*
    (or default settings if *config* is ``None``).  Subsequent calls ignore
    *config* and return the existing instance.

    Parameters
    ----------
    config:
        Optional :class:`GlobalRiskConfig` used only on the first call.

    Returns
    -------
    GlobalRiskController
    """
    global _controller
    if _controller is None:
        with _controller_lock:
            if _controller is None:
                _controller = GlobalRiskController(config=config)
    return _controller


def reset_global_risk_controller() -> None:
    """Destroy the singleton (intended for testing only)."""
    global _controller
    with _controller_lock:
        if _controller is not None:
            _controller.stop_background_monitor()
            _controller = None
