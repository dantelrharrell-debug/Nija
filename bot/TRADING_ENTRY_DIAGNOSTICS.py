"""
NIJA Trade Entry & Fill Diagnostics
====================================

Runtime visibility into why trades are not entering or filling.
Emits structured diagnostic events on every trade attempt.

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("nija.trading_entry_diagnostics")


class TradeEntryBlocker:
    """Tracks conditions that prevent trade entry."""

    def __init__(self):
        self._lock = threading.Lock()
        self._blockers: dict[str, float] = {}  # reason -> timestamp of first blockage
        self._resolved: dict[str, float] = {}  # reason -> timestamp of resolution
        
    def block(self, reason: str) -> None:
        """Record a new or persistent trade-entry blocker."""
        with self._lock:
            if reason not in self._blockers:
                self._blockers[reason] = time.time()
                self._resolved.pop(reason, None)
                logger.critical(f"🛑 TRADE ENTRY BLOCKED: {reason}")
                
    def unblock(self, reason: str) -> None:
        """Clear a previously recorded blocker."""
        with self._lock:
            if reason in self._blockers:
                del self._blockers[reason]
                self._resolved[reason] = time.time()
                logger.info(f"✅ TRADE ENTRY UNBLOCKED: {reason}")
    
    def is_blocked(self) -> bool:
        """Return True if any blocker is active."""
        with self._lock:
            return bool(self._blockers)
    
    def reasons(self) -> list[str]:
        """Return list of active blocker reasons."""
        with self._lock:
            return list(self._blockers.keys())
    
    def duration_s(self, reason: str) -> Optional[float]:
        """Return how long this reason has been blocking (or None if not blocking)."""
        with self._lock:
            if reason not in self._blockers:
                return None
            return time.time() - self._blockers[reason]


class TradeEntryDiagnostics:
    """Structured diagnostics for trade-entry and fill failures."""

    def __init__(self):
        self._lock = threading.Lock()
        self._blocker = TradeEntryBlocker()
        self._last_attempt_ts: float = 0.0
        self._last_attempt_reason: str = ""
        self._attempt_count: int = 0
        self._success_count: int = 0
        
    def record_attempt(self, reason_blocked: Optional[str] = None) -> None:
        """Record a trade-entry attempt (success or blocked)."""
        with self._lock:
            self._last_attempt_ts = time.time()
            self._attempt_count += 1
            
            if reason_blocked:
                self._last_attempt_reason = reason_blocked
                self._blocker.block(reason_blocked)
                logger.warning(
                    f"⚠️  TRADE ENTRY ATTEMPT BLOCKED: {reason_blocked} "
                    f"(attempt #{self._attempt_count})"
                )
            else:
                self._success_count += 1
                self._last_attempt_reason = "success"
                logger.info(
                    f"✅ TRADE ENTRY ATTEMPT SUCCEEDED (success #{self._success_count})"
                )
    
    def authority_degraded(self, detail: str) -> None:
        """Mark authority as degraded (lock contention, generation mismatch, etc)."""
        reason = f"authority_degraded:{detail}"
        self._blocker.block(reason)
        logger.critical(f"⚠️  AUTHORITY DEGRADATION: {detail}")
    
    def authority_restored(self, detail: str) -> None:
        """Clear authority degradation."""
        reason = f"authority_degraded:{detail}"
        self._blocker.unblock(reason)
        logger.info(f"✅ AUTHORITY RESTORED: {detail}")
    
    def kraken_hard_stop(self, reason: str) -> None:
        """Record Kraken hard-stop (nonce authority lost, connection failed)."""
        blocker_reason = f"kraken_hard_stop:{reason}"
        self._blocker.block(blocker_reason)
        logger.critical(f"🛑 KRAKEN HARD STOP: {reason}")
    
    def kraken_restored(self) -> None:
        """Record Kraken restoration."""
        self._blocker.unblock("kraken_hard_stop:*")
        logger.info("✅ KRAKEN RESTORED")
    
    def insufficient_capital(self, balance: float, minimum: float) -> None:
        """Record capital insufficiency."""
        reason = f"insufficient_capital:balance={balance:.2f} required={minimum:.2f}"
        self._blocker.block(reason)
        logger.warning(f"💰 {reason}")
    
    def capital_available(self) -> None:
        """Clear capital insufficiency."""
        self._blocker.unblock("insufficient_capital:*")
        logger.info("✅ CAPITAL AVAILABLE")
    
    def get_status(self) -> dict:
        """Return current diagnostics status."""
        with self._lock:
            return {
                "is_blocked": self._blocker.is_blocked(),
                "blockers": self._blocker.reasons(),
                "attempt_count": self._attempt_count,
                "success_count": self._success_count,
                "success_rate": self._success_count / max(1, self._attempt_count),
                "last_attempt_ts": self._last_attempt_ts,
                "last_attempt_reason": self._last_attempt_reason,
            }


# Process-global singleton
_diagnostics_instance: Optional[TradeEntryDiagnostics] = None
_diagnostics_lock = threading.Lock()


def get_trade_entry_diagnostics() -> TradeEntryDiagnostics:
    """Return the process-global TradeEntryDiagnostics singleton."""
    global _diagnostics_instance
    if _diagnostics_instance is not None:
        return _diagnostics_instance
    with _diagnostics_lock:
        if _diagnostics_instance is None:
            _diagnostics_instance = TradeEntryDiagnostics()
    return _diagnostics_instance


__all__ = [
    "TradeEntryBlocker",
    "TradeEntryDiagnostics",
    "get_trade_entry_diagnostics",
]
