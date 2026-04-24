"""
Latency Drift Guard — Leak #2 fix
===================================
Timestamps the moment a trade signal fires and compares it against the price
when the order is eventually submitted.  If the market has moved by more than a
configurable *max_drift_pct* during that window the signal is cancelled — the
edge identified at analysis time is likely gone.

How to use
----------
::

    from bot.latency_drift_guard import get_latency_drift_guard

    guard = get_latency_drift_guard()

    # 1. When the signal is first generated (analysis stage):
    token = guard.stamp_signal(symbol, analysis_price)

    # 2. Just before placing the order (execution stage):
    ok, reason = guard.check_drift(token, current_execution_price)
    if not ok:
        logger.warning("Signal cancelled — price drifted: %s", reason)
        continue

    # 3. After fill (optional — cleans up the token):
    guard.clear(token)

Design notes
------------
* Tokens are UUIDs; no persistent state is needed.
* Thread-safe via a simple dict + lock.
* Drift is measured as ``abs(exec_price - signal_price) / signal_price``.
* An additional *max_age_seconds* guard rejects signals that have been waiting
  too long even if the price hasn't moved (stale signal).

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger("nija.latency_drift_guard")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Reject signal if price moved more than this fraction since analysis
DEFAULT_MAX_DRIFT_PCT: float = 0.005   # 0.5%
# Reject signal if execution hasn't happened within this many seconds
DEFAULT_MAX_AGE_SECONDS: float = 60.0  # 1 minute


@dataclass
class SignalStamp:
    token: str
    symbol: str
    signal_price: float
    stamped_at: float = field(default_factory=time.monotonic)


@dataclass
class DriftResult:
    approved: bool
    token: str
    symbol: str
    signal_price: float
    execution_price: float
    drift_pct: float
    age_seconds: float
    reason: str


class LatencyDriftGuard:
    """Detects and rejects signals where price has drifted since analysis."""

    def __init__(
        self,
        max_drift_pct: float = DEFAULT_MAX_DRIFT_PCT,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        enabled: bool = True,
    ) -> None:
        self.max_drift_pct = max_drift_pct
        self.max_age_seconds = max_age_seconds
        self.enabled = enabled
        self._stamps: Dict[str, SignalStamp] = {}
        self._lock = threading.Lock()
        logger.info(
            "⏱️  Latency Drift Guard initialised | max_drift=%.2f%% | max_age=%.0fs",
            max_drift_pct * 100,
            max_age_seconds,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stamp_signal(self, symbol: str, signal_price: float) -> str:
        """
        Record the price at the moment a signal fires.

        Returns a *token* string that must be passed to :meth:`check_drift`
        and (optionally) :meth:`clear`.
        """
        token = str(uuid.uuid4())
        stamp = SignalStamp(token=token, symbol=symbol, signal_price=signal_price)
        with self._lock:
            self._stamps[token] = stamp
        logger.debug(
            "📍 Signal stamped: %s @ $%.6f (token=%s)",
            symbol, signal_price, token[:8],
        )
        return token

    def check_drift(
        self,
        token: str,
        execution_price: float,
    ) -> Tuple[bool, str]:
        """
        Compare *execution_price* against the stamped signal price.

        Returns ``(True, "ok")`` when drift is within limits, otherwise
        ``(False, reason_string)`` — caller should cancel the order.
        """
        if not self.enabled:
            return True, "guard disabled"

        with self._lock:
            stamp = self._stamps.get(token)

        if stamp is None:
            logger.warning("⚠️  Drift guard: unknown token %s — allowing trade", token[:8])
            return True, "unknown token"

        age = time.monotonic() - stamp.stamped_at

        if age > self.max_age_seconds:
            reason = (
                f"signal age {age:.1f}s > max {self.max_age_seconds:.0f}s for {stamp.symbol}"
            )
            logger.warning("🚫 LATENCY DRIFT: %s (stale signal)", reason)
            self.clear(token)
            return False, reason

        if stamp.signal_price <= 0:
            return True, "zero signal price — skipping drift check"

        drift = abs(execution_price - stamp.signal_price) / stamp.signal_price

        result = DriftResult(
            approved=drift <= self.max_drift_pct,
            token=token,
            symbol=stamp.symbol,
            signal_price=stamp.signal_price,
            execution_price=execution_price,
            drift_pct=drift,
            age_seconds=age,
            reason="",
        )

        if not result.approved:
            result.reason = (
                f"{stamp.symbol} price drifted {drift*100:.3f}% in {age:.1f}s "
                f"(signal ${stamp.signal_price:.6f} → exec ${execution_price:.6f}, "
                f"limit {self.max_drift_pct*100:.2f}%)"
            )
            logger.warning("🚫 LATENCY DRIFT GUARD: %s", result.reason)
            self.clear(token)
        else:
            logger.debug(
                "✅ Drift OK: %s | %.3f%% in %.1fs",
                stamp.symbol, drift * 100, age,
            )

        return result.approved, result.reason

    def clear(self, token: str) -> None:
        """Remove the stamp for *token* (call after fill or cancellation)."""
        with self._lock:
            self._stamps.pop(token, None)

    def purge_stale(self) -> int:
        """Remove all stamps older than *max_age_seconds*. Returns count purged."""
        now = time.monotonic()
        with self._lock:
            stale = [
                t for t, s in self._stamps.items()
                if now - s.stamped_at > self.max_age_seconds
            ]
            for t in stale:
                self._stamps.pop(t, None)
        if stale:
            logger.debug("🧹 Drift guard purged %d stale stamps", len(stale))
        return len(stale)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[LatencyDriftGuard] = None


def get_latency_drift_guard(
    max_drift_pct: float = DEFAULT_MAX_DRIFT_PCT,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    enabled: bool = True,
) -> LatencyDriftGuard:
    """Return the process-wide singleton, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = LatencyDriftGuard(
            max_drift_pct=max_drift_pct,
            max_age_seconds=max_age_seconds,
            enabled=enabled,
        )
    return _instance
