"""
NIJA Global Portfolio Kill Switch
===================================

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
