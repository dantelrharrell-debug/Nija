"""
NIJA Global Portfolio Kill Switch

Master safety breaker for the entire NIJA trading system.

When a catastrophic event occurs, the kill switch:
    - Stops opening new trades immediately
    - Signals all subsystems to cancel open orders
    - Optionally triggers position closure (exit-only mode)
    - Locks the trading engine until manually reset

Trigger conditions
------------------
1. **Portfolio drawdown** exceeds a hard limit (default −35 %)
2. **Risk engine** reports a corrupted or inconsistent state
3. **Exchange outage** has lasted too long (via exchange_outage_guard)
4. **Capital mismatch** — broker-reported balance diverges from expected

Architecture
------------
::

    trade cycle
         ↓
    risk engine
         ↓
    kill switch check  ← PortfolioKillSwitch.is_trading_halted()
         ↓
    if triggered → halt trading (no new entries; optional exit-only mode)

Integration
-----------
Wraps and delegates to the low-level ``bot/kill_switch.py`` ``KillSwitch``
while adding portfolio-level trigger logic.  Exposes a clean API that other
subsystems can query without knowing internals.
NIJA Portfolio Kill Switch

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
    if pks.is_trading_halted():
        return

    # Update portfolio balance each cycle
    pks.update_balance(current_balance=9_500.0, initial_capital=10_000.0)

    # Signal a risk-engine corruption
    pks.signal_risk_engine_corrupt("Inconsistent position state detected")

    # Signal exchange outage
    pks.signal_exchange_outage("Exchange offline for 15 minutes")

    # Manual reset (admin action only)
    pks.manual_reset("Reviewed and confirmed — safe to resume")
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

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("nija.portfolio_kill_switch")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class HaltReason(Enum):
    """Why the portfolio kill switch was triggered."""
    DRAWDOWN = "DRAWDOWN"
    RISK_ENGINE_CORRUPT = "RISK_ENGINE_CORRUPT"
    EXCHANGE_OUTAGE = "EXCHANGE_OUTAGE"
    CAPITAL_MISMATCH = "CAPITAL_MISMATCH"
    MANUAL = "MANUAL"


class HaltMode(Enum):
    """Severity of the halt."""
    NO_NEW_ENTRIES = "NO_NEW_ENTRIES"   # Existing positions managed; no new trades
    EXIT_ONLY = "EXIT_ONLY"             # Attempt to close all open positions
    FULL_STOP = "FULL_STOP"             # Absolute halt — no trade operations at all


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PortfolioKillSwitchConfig:
    """All configurable thresholds for the Portfolio Kill Switch.

    Attributes
    ----------
    drawdown_hard_limit_pct:
        Trigger a full halt when portfolio drawdown from peak exceeds this
        percentage (positive number, compared against negative P&L).
        Default: 35.0 (−35 %).
    capital_mismatch_pct:
        Trigger when broker-reported balance diverges from the internally
        tracked expected balance by more than this percentage.
        Default: 20.0 (20 %).
    exchange_outage_auto_trigger:
        If True, the portfolio kill switch will accept outage signals from
        ``ExchangeOutageGuard`` and halt trading automatically.
        Default: True.
    default_halt_mode:
        The ``HaltMode`` applied when the kill switch fires.
        Default: ``HaltMode.NO_NEW_ENTRIES``.
    lock_until_manual_reset:
        If True (recommended), the kill switch stays locked after a trigger
        and can only be cleared by an explicit ``manual_reset()`` call.
        If False, the switch auto-clears when conditions improve.
        Default: True.
    """
    drawdown_hard_limit_pct: float = 35.0
    capital_mismatch_pct: float = 20.0
    exchange_outage_auto_trigger: bool = True
    default_halt_mode: HaltMode = HaltMode.NO_NEW_ENTRIES
    lock_until_manual_reset: bool = True


# ---------------------------------------------------------------------------
# Trigger event record
# ---------------------------------------------------------------------------

@dataclass
class TriggerEvent:
    """Immutable record of a single trigger activation."""
    timestamp: str
    reason: HaltReason
    detail: str
    halt_mode: str


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PortfolioKillSwitch:
    """Global portfolio kill switch — master safety breaker.

    Thread-safe.  Use ``get_portfolio_kill_switch()`` for the singleton.
    """

    def __init__(
        self,
        config: Optional[PortfolioKillSwitchConfig] = None,
    ) -> None:
        self._config = config or PortfolioKillSwitchConfig()
        self._lock = threading.RLock()

        # Halt state
        self._halted: bool = False
        self._halt_reason: Optional[HaltReason] = None
        self._halt_detail: str = ""
        self._halt_mode: HaltMode = self._config.default_halt_mode

        # Audit trail
        self._trigger_history: List[TriggerEvent] = []

        # Balance / drawdown tracking
        self._peak_balance: Optional[float] = None
        self._last_known_balance: Optional[float] = None
        self._expected_balance: Optional[float] = None  # internal expectation

        # Callbacks fired on trigger / reset
        self._on_trigger_callbacks: List[Callable[[HaltReason, str, HaltMode], None]] = []
        self._on_reset_callbacks: List[Callable[[str], None]] = []

        # Integration with low-level kill_switch
        self._low_level_ks = self._load_kill_switch()

        logger.info(
            "🛑 PortfolioKillSwitch initialised | drawdown_limit=%.1f%% | "
            "lock_until_manual_reset=%s",
            self._config.drawdown_hard_limit_pct,
            self._config.lock_until_manual_reset,
        )

    # ------------------------------------------------------------------
    # Lazy integration helpers
    # ------------------------------------------------------------------

    def _load_kill_switch(self):
        """Load the low-level KillSwitch singleton (graceful if absent)."""
        try:
            from bot.kill_switch import get_kill_switch
            return get_kill_switch()
        except Exception:
            try:
                from kill_switch import get_kill_switch  # type: ignore
                return get_kill_switch()
            except Exception:
                logger.warning(
                    "⚠️  Low-level KillSwitch unavailable — "
                    "portfolio kill switch will operate independently"
                )
                return None

    def _engage_low_level(self, reason: str) -> None:
        """Forward the trigger to the low-level KillSwitch if available."""
        if self._low_level_ks is not None:
            try:
                self._low_level_ks.activate(reason, "PORTFOLIO_KILL_SWITCH")
            except Exception as exc:
                logger.error("❌ Could not activate low-level kill switch: %s", exc)

    # ------------------------------------------------------------------
    # Core trigger logic
    # ------------------------------------------------------------------

    def _trigger(
        self,
        reason: HaltReason,
        detail: str,
        mode: Optional[HaltMode] = None,
    ) -> None:
        """Internal: record a trigger event and engage the halt."""
        halt_mode = mode or self._config.default_halt_mode
        with self._lock:
            if self._halted and self._config.lock_until_manual_reset:
                # Already halted — do not overwrite with a lower-severity trigger
                logger.warning(
                    "⚠️  Kill switch already active (reason=%s) — "
                    "new trigger '%s' suppressed until manual reset",
                    self._halt_reason,
                    reason,
                )
                return

            self._halted = True
            self._halt_reason = reason
            self._halt_detail = detail
            self._halt_mode = halt_mode

            event = TriggerEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                reason=reason,
                detail=detail,
                halt_mode=halt_mode.value,
            )
            self._trigger_history.append(event)

        logger.critical(
            "🚨 PORTFOLIO KILL SWITCH TRIGGERED | reason=%s | mode=%s | %s",
            reason.value,
            halt_mode.value,
            detail,
        )

        # Notify the low-level kill switch
        self._engage_low_level(f"[{reason.value}] {detail}")

        # Fire callbacks
        for cb in self._on_trigger_callbacks:
            try:
                cb(reason, detail, halt_mode)
            except Exception as exc:
                logger.error("❌ on_trigger callback error: %s", exc)

    # ------------------------------------------------------------------
    # Public trigger methods
    # ------------------------------------------------------------------

    def trigger_drawdown(
        self,
        current_drawdown_pct: float,
        current_balance: float,
        peak_balance: float,
    ) -> None:
        """Trigger because portfolio drawdown exceeded the hard limit.

        Parameters
        ----------
        current_drawdown_pct:
            Current peak-to-trough drawdown expressed as a positive
            percentage (e.g. ``35.5`` for −35.5 %).
        current_balance, peak_balance:
            Balances used to build the human-readable detail string.
        """
        detail = (
            f"Portfolio drawdown {current_drawdown_pct:.2f}% ≥ limit "
            f"{self._config.drawdown_hard_limit_pct:.0f}% — "
            f"balance ${current_balance:,.2f} vs peak ${peak_balance:,.2f}"
        )
        self._trigger(HaltReason.DRAWDOWN, detail, HaltMode.EXIT_ONLY)

    def signal_risk_engine_corrupt(self, description: str) -> None:
        """Trigger because the risk engine reported an inconsistent state.

        Parameters
        ----------
        description:
            Human-readable description of the corruption (logged verbatim).
        """
        detail = f"Risk engine corruption detected: {description}"
        self._trigger(HaltReason.RISK_ENGINE_CORRUPT, detail, HaltMode.FULL_STOP)

    def signal_exchange_outage(self, description: str) -> None:
        """Trigger because of a prolonged exchange outage.

        Only fires if ``config.exchange_outage_auto_trigger`` is True.

        Parameters
        ----------
        description:
            Human-readable outage description.
        """
        if not self._config.exchange_outage_auto_trigger:
            logger.debug(
                "PortfolioKillSwitch: exchange outage signal ignored "
                "(exchange_outage_auto_trigger=False)"
            )
            return
        detail = f"Exchange outage: {description}"
        self._trigger(HaltReason.EXCHANGE_OUTAGE, detail, HaltMode.NO_NEW_ENTRIES)

    def signal_capital_mismatch(
        self,
        expected_balance: float,
        broker_balance: float,
    ) -> None:
        """Trigger because the broker-reported balance diverges unexpectedly.

        Only fires when the absolute relative divergence exceeds
        ``config.capital_mismatch_pct``.

        Parameters
        ----------
        expected_balance:
            Balance the system internally expects.
        broker_balance:
            Balance reported by the broker API.
        """
        if expected_balance <= 0:
            return
        divergence_pct = abs(broker_balance - expected_balance) / expected_balance * 100
        if divergence_pct >= self._config.capital_mismatch_pct:
            detail = (
                f"Capital mismatch: expected ${expected_balance:,.2f} "
                f"but broker reports ${broker_balance:,.2f} "
                f"({divergence_pct:.1f}% divergence ≥ "
                f"{self._config.capital_mismatch_pct:.0f}% threshold)"
            )
            self._trigger(HaltReason.CAPITAL_MISMATCH, detail, HaltMode.FULL_STOP)

    def trigger_manual(self, reason: str) -> None:
        """Manually trigger the kill switch (operator action).
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
            Human-readable reason for manual activation.
        """
        self._trigger(HaltReason.MANUAL, reason, HaltMode.NO_NEW_ENTRIES)

    # ------------------------------------------------------------------
    # Balance / drawdown monitoring
    # ------------------------------------------------------------------

    def update_balance(
        self,
        current_balance: float,
        initial_capital: Optional[float] = None,
    ) -> bool:
        """Record the current balance and check the drawdown hard limit.

        Call this on every trading cycle.  If the drawdown limit is breached
        the kill switch is triggered automatically.

        Parameters
        ----------
        current_balance:
            Current portfolio value in USD.
        initial_capital:
            If provided and the peak has not been set yet, this is used as
            the initial peak.  Subsequent peaks are updated automatically.

        Returns
        -------
        bool
            True if the kill switch was triggered by this call.
        """
        with self._lock:
            # Initialise peak
            if self._peak_balance is None:
                self._peak_balance = max(current_balance, initial_capital or current_balance)

            # Update peak on new highs
            if current_balance > self._peak_balance:
                self._peak_balance = current_balance

            peak = self._peak_balance
            self._last_known_balance = current_balance

        # Check drawdown
        if peak > 0:
            drawdown_pct = (peak - current_balance) / peak * 100
            if drawdown_pct >= self._config.drawdown_hard_limit_pct:
                self.trigger_drawdown(drawdown_pct, current_balance, peak)
                return True

        return False

    def check_capital_mismatch(
        self,
        expected_balance: float,
        broker_balance: float,
    ) -> bool:
        """Check for capital mismatch and trigger if threshold exceeded.

        Parameters
        ----------
        expected_balance, broker_balance:
            See ``signal_capital_mismatch``.

        Returns
        -------
        bool
            True if the kill switch was triggered.
        """
        if expected_balance <= 0:
            return False
        divergence_pct = abs(broker_balance - expected_balance) / expected_balance * 100
        if divergence_pct >= self._config.capital_mismatch_pct:
            self.signal_capital_mismatch(expected_balance, broker_balance)
            return True
        return False

    # ------------------------------------------------------------------
    # Gate API — call this before every trade
    # ------------------------------------------------------------------

    def is_trading_halted(self) -> bool:
        """Return True if the kill switch is active and new entries are blocked.

        This is the **primary gate** — call before placing any new trade.
        """
        with self._lock:
            return self._halted

    def is_exits_allowed(self) -> bool:
        """Return True if exit orders are allowed under the current halt mode.

        Exits are blocked only in ``FULL_STOP`` mode.
        """
        with self._lock:
            if not self._halted:
                return True
            return self._halt_mode != HaltMode.FULL_STOP

    def assert_not_halted(self, operation: str = "trade") -> None:
        """Raise ``RuntimeError`` if the kill switch is active.

        Parameters
        ----------
        operation:
            Description of the attempted operation (included in the error).
        """
        if self.is_trading_halted():
            with self._lock:
                reason = self._halt_reason
                detail = self._halt_detail
            msg = (
                f"Cannot perform '{operation}': "
                f"PortfolioKillSwitch is active "
                f"(reason={reason.value if reason else 'UNKNOWN'} — {detail})"
            )
            logger.error("🚨 %s", msg)
            raise RuntimeError(msg)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def manual_reset(self, reason: str = "Manual reset") -> None:
        """Clear the kill switch (operator action).

        This is the **only** way to resume trading when
        ``config.lock_until_manual_reset`` is True.

        Parameters
        ----------
        reason:
            Human-readable reason for the reset.
        """
        with self._lock:
            was_halted = self._halted
            self._halted = False
            self._halt_reason = None
            self._halt_detail = ""

        logger.warning("🔓 PortfolioKillSwitch RESET | reason='%s' | was_halted=%s", reason, was_halted)

        # Also reset low-level kill switch
        if self._low_level_ks is not None:
            try:
                self._low_level_ks.deactivate(reason)
            except Exception as exc:
                logger.error("❌ Could not deactivate low-level kill switch: %s", exc)

        # Fire callbacks
        for cb in self._on_reset_callbacks:
            try:
                cb(reason)
            except Exception as exc:
                logger.error("❌ on_reset callback error: %s", exc)

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def register_on_trigger(
        self,
        callback: Callable[[HaltReason, str, HaltMode], None],
    ) -> None:
        """Register a callback invoked when the kill switch triggers.

        Parameters
        ----------
        callback:
            Callable receiving ``(reason: HaltReason, detail: str, mode: HaltMode)``.
        """
        self._on_trigger_callbacks.append(callback)

    def register_on_reset(self, callback: Callable[[str], None]) -> None:
        """Register a callback invoked when the kill switch is reset.

        Parameters
        ----------
        callback:
            Callable receiving ``(reset_reason: str)``.
        """
        self._on_reset_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return a JSON-serialisable status snapshot."""
        with self._lock:
            return {
                "halted": self._halted,
                "halt_reason": self._halt_reason.value if self._halt_reason else None,
                "halt_detail": self._halt_detail,
                "halt_mode": self._halt_mode.value,
                "peak_balance": self._peak_balance,
                "last_known_balance": self._last_known_balance,
                "drawdown_hard_limit_pct": self._config.drawdown_hard_limit_pct,
                "lock_until_manual_reset": self._config.lock_until_manual_reset,
                "trigger_count": len(self._trigger_history),
                "last_trigger": (
                    {
                        "timestamp": self._trigger_history[-1].timestamp,
                        "reason": self._trigger_history[-1].reason.value,
                        "detail": self._trigger_history[-1].detail,
                    }
                    if self._trigger_history
                    else None
                ),
            }
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
    """Return (or create) the global ``PortfolioKillSwitch`` singleton.

    Parameters
    ----------
    config:
        Optional configuration; only used on the **first** call.
        Subsequent calls return the existing instance regardless of ``config``.
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
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

    cfg = PortfolioKillSwitchConfig(
        drawdown_hard_limit_pct=35.0,
        capital_mismatch_pct=20.0,
        lock_until_manual_reset=True,
    )
    pks = PortfolioKillSwitch(cfg)

    print("\n=== Portfolio Kill Switch — smoke test ===\n")

    # Normal operation
    triggered = pks.update_balance(10_000.0, initial_capital=10_000.0)
    print(f"After init update — halted: {pks.is_trading_halted()}, triggered: {triggered}")

    # Simulate healthy growth
    triggered = pks.update_balance(11_000.0)
    print(f"After growth — halted: {pks.is_trading_halted()}, triggered: {triggered}")

    # Simulate catastrophic drawdown (peak=11_000, balance=7_000 → 36.4%)
    triggered = pks.update_balance(7_000.0)
    print(f"After drawdown — halted: {pks.is_trading_halted()}, triggered: {triggered}")
    print(f"Status: {pks.get_status()}")

    # Manual reset
    pks.manual_reset("System reviewed — safe to resume")
    print(f"\nAfter reset — halted: {pks.is_trading_halted()}")

    # Capital mismatch
    triggered2 = pks.check_capital_mismatch(expected_balance=10_000.0, broker_balance=7_000.0)
    print(f"\nCapital mismatch test — triggered: {triggered2}")
    print("\n✅ Smoke test complete")
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
