"""
NIJA Trade Duplication Guard
=============================

Prevents the same trade from being submitted more than once within a
configurable time window.

This guard is an additional safety layer on top of broker-side idempotency
keys.  It blocks duplicates that arise from:

* Webhook retries / duplicate HTTP deliveries.
* Signal fan-out bugs where the same alert fires more than once.
* Race conditions in multi-threaded execution engines.
* Network retries that mistakenly re-submit an order.

Architecture
------------
* Each pending trade is fingerprinted from ``(symbol, side, rounded_size,
  account_id)``.  Price is intentionally *excluded* because market-order
  prices are unknown at submission time.
* Fingerprints are registered with a TTL.  After the TTL expires the slot is
  automatically freed so a fresh order with identical parameters is permitted.
* Background reaper thread evicts expired entries periodically.
* Thread-safe throughout (single ``threading.Lock``).
* Singleton via ``get_trade_duplication_guard()``.

Usage
-----
::

    from bot.trade_duplication_guard import get_trade_duplication_guard

    guard = get_trade_duplication_guard()

    # Before submitting an order:
    allowed, reason = guard.check_and_register(
        symbol="BTC-USD",
        side="buy",
        size=0.001,
        account_id="acc_123",
    )
    if not allowed:
        logger.warning("Duplicate trade blocked: %s", reason)
        return  # do not submit

    try:
        broker.place_order(...)
    finally:
        # Release the slot so the next *legitimate* order can proceed
        guard.release(symbol="BTC-USD", side="buy", size=0.001, account_id="acc_123")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.trade_duplication_guard")

_MAX_BLOCKED_LOG_SIZE: int = 200   # maximum number of blocked-attempt records kept in memory

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class TradeDuplicationGuardConfig:
    """Configuration for the trade deduplication guard."""

    # How long (seconds) a fingerprint is held after registration.
    # Any identical trade within this window is rejected as a duplicate.
    ttl_seconds: float = 60.0

    # Round trade size to this many decimal places when fingerprinting.
    # Prevents float noise (e.g. 0.0010000001 vs 0.001) from creating
    # distinct fingerprints for what is logically the same order.
    size_decimals: int = 6

    # Safety cap on the number of concurrently held fingerprints.
    max_pending: int = 500

    # How often (seconds) the background reaper purges expired entries.
    # Set to 0 to disable (entries still expire lazily on access).
    cleanup_interval_seconds: float = 30.0


# ---------------------------------------------------------------------------
# Internal slot record
# ---------------------------------------------------------------------------


@dataclass
class _Slot:
    """A registered, in-flight trade fingerprint."""

    fingerprint: str
    symbol: str
    side: str
    size: float
    account_id: str
    registered_at: float    # monotonic-clock seconds
    expires_at: float        # monotonic-clock seconds
    submission_count: int = 1


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


class TradeDuplicationGuard:
    """Thread-safe trade deduplication guard.

    Use :func:`get_trade_duplication_guard` to obtain the global singleton.
    """

    def __init__(self, config: Optional[TradeDuplicationGuardConfig] = None) -> None:
        self._cfg = config or TradeDuplicationGuardConfig()
        self._lock = threading.Lock()
        self._slots: Dict[str, _Slot] = {}   # fingerprint → slot
        self._blocked_log: List[Dict] = []   # recent blocked attempts (capped at _MAX_BLOCKED_LOG_SIZE)

        # Background cleanup thread
        self._stop_cleanup = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None
        if self._cfg.cleanup_interval_seconds > 0:
            self._start_cleanup_thread()

        logger.info(
            "🔒 Trade Duplication Guard initialised (TTL=%.0fs, max_pending=%d)",
            self._cfg.ttl_seconds,
            self._cfg.max_pending,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_register(
        self,
        symbol: str,
        side: str,
        size: float,
        account_id: str = "",
    ) -> Tuple[bool, str]:
        """Check whether the trade is a duplicate and, if not, register it.

        Parameters
        ----------
        symbol:
            Instrument identifier (e.g. ``"BTC-USD"``).
        side:
            ``"buy"`` or ``"sell"``.
        size:
            Order quantity.
        account_id:
            Account or sub-account identifier.  Pass ``""`` for single-account
            setups — the guard still deduplicates correctly.

        Returns
        -------
        (allowed, reason):
            ``allowed=True`` means the trade is **not** a duplicate and has been
            registered.  ``allowed=False`` means it **is** a duplicate; ``reason``
            explains why it was blocked.
        """
        fp = self._fingerprint(symbol, side, size, account_id)
        now = time.monotonic()

        with self._lock:
            # Lazily evict an expired slot for this specific fingerprint first
            existing = self._slots.get(fp)
            if existing is not None and now >= existing.expires_at:
                del self._slots[fp]
                existing = None

            if existing is not None:
                # Duplicate detected
                existing.submission_count += 1
                age_ms = (now - existing.registered_at) * 1_000
                reason = (
                    f"Duplicate trade blocked: {symbol} {side} "
                    f"{size:.{self._cfg.size_decimals}f} already registered "
                    f"{age_ms:.0f} ms ago "
                    f"(attempt #{existing.submission_count})"
                )
                entry = {
                    "fingerprint": fp,
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "account_id": account_id,
                    "blocked_at": datetime.now(timezone.utc).isoformat(),
                    "age_ms": round(age_ms),
                    "submission_count": existing.submission_count,
                }
                self._blocked_log.append(entry)
                if len(self._blocked_log) > _MAX_BLOCKED_LOG_SIZE:
                    self._blocked_log = self._blocked_log[-_MAX_BLOCKED_LOG_SIZE:]
                logger.warning("🚫 %s", reason)
                return False, reason

            # Check capacity; attempt eager cleanup if full
            if len(self._slots) >= self._cfg.max_pending:
                self._evict_expired_locked(now)
                if len(self._slots) >= self._cfg.max_pending:
                    reason = (
                        f"Trade rejected: guard at capacity "
                        f"({self._cfg.max_pending} pending slots); "
                        "possible runaway order submission"
                    )
                    logger.error("❌ %s", reason)
                    return False, reason

            # Register the fingerprint
            slot = _Slot(
                fingerprint=fp,
                symbol=symbol,
                side=side,
                size=size,
                account_id=account_id,
                registered_at=now,
                expires_at=now + self._cfg.ttl_seconds,
            )
            self._slots[fp] = slot

        logger.debug(
            "✅ Trade registered: %s %s %.6f [%s]", symbol, side, size, account_id
        )
        return True, "ok"

    def release(
        self,
        symbol: str,
        side: str,
        size: float,
        account_id: str = "",
    ) -> bool:
        """Release a previously registered trade fingerprint.

        Call this once the order has been filled, cancelled, or definitively
        rejected so that a fresh order with identical parameters may be placed.

        Returns
        -------
        bool:
            ``True`` if the fingerprint was found and removed; ``False`` if it
            was not registered (already expired or never registered).
        """
        fp = self._fingerprint(symbol, side, size, account_id)
        with self._lock:
            if fp in self._slots:
                del self._slots[fp]
                logger.debug(
                    "🔓 Trade fingerprint released: %s %s %.6f [%s]",
                    symbol, side, size, account_id,
                )
                return True
        logger.debug(
            "Trade fingerprint not found (already expired?): %s %s %.6f [%s]",
            symbol, side, size, account_id,
        )
        return False

    def is_duplicate(
        self,
        symbol: str,
        side: str,
        size: float,
        account_id: str = "",
    ) -> bool:
        """Check if a trade would be a duplicate *without* registering it.

        Useful for read-only inspection or pre-flight checks.
        """
        fp = self._fingerprint(symbol, side, size, account_id)
        now = time.monotonic()
        with self._lock:
            slot = self._slots.get(fp)
            return slot is not None and now < slot.expires_at

    def get_status(self) -> Dict:
        """Return current guard status for dashboards and health checks."""
        now = time.monotonic()
        with self._lock:
            active_count = sum(1 for s in self._slots.values() if now < s.expires_at)
            return {
                "pending_fingerprints": active_count,
                "max_pending": self._cfg.max_pending,
                "ttl_seconds": self._cfg.ttl_seconds,
                "total_blocked": len(self._blocked_log),
                "recent_blocked": self._blocked_log[-10:],
            }

    def reset(self) -> None:
        """Clear all registered fingerprints and the blocked-attempt log.

        Intended for testing or emergency resets only.
        """
        with self._lock:
            self._slots.clear()
            self._blocked_log.clear()
        logger.warning("🔄 Trade Duplication Guard reset — all fingerprints cleared")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fingerprint(
        self, symbol: str, side: str, size: float, account_id: str
    ) -> str:
        """Generate a stable string fingerprint for the trade parameters."""
        rounded = round(size, self._cfg.size_decimals)
        return (
            f"{account_id}:{symbol.upper()}:{side.lower()}:"
            f"{rounded:.{self._cfg.size_decimals}f}"
        )

    def _evict_expired_locked(self, now: float) -> int:
        """Remove expired slots.  *Must* be called with ``self._lock`` held."""
        expired = [fp for fp, s in self._slots.items() if now >= s.expires_at]
        for fp in expired:
            del self._slots[fp]
        return len(expired)

    def _cleanup_loop(self) -> None:
        """Background thread: periodically evict expired fingerprints."""
        interval = self._cfg.cleanup_interval_seconds
        while not self._stop_cleanup.wait(interval):
            now = time.monotonic()
            with self._lock:
                evicted = self._evict_expired_locked(now)
            if evicted:
                logger.debug("🧹 Evicted %d expired trade fingerprints", evicted)

    def _start_cleanup_thread(self) -> None:
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="TradeDupGuardCleaner",
            daemon=True,
        )
        self._cleanup_thread.start()

    def __del__(self) -> None:
        if hasattr(self, "_stop_cleanup"):
            self._stop_cleanup.set()


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[TradeDuplicationGuard] = None
_instance_lock = threading.Lock()


def get_trade_duplication_guard(
    config: Optional[TradeDuplicationGuardConfig] = None,
) -> TradeDuplicationGuard:
    """Return the global singleton :class:`TradeDuplicationGuard`.

    The first caller may optionally supply a
    :class:`TradeDuplicationGuardConfig` to customise behaviour.  Subsequent
    callers receive the same instance regardless of the ``config`` argument.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TradeDuplicationGuard(config)
    return _instance
