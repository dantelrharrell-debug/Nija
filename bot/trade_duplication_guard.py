"""
NIJA Trade Duplication Guard

Prevents duplicate orders caused by network retries, thread race conditions,
or signal timing issues.

The problem
-----------
A trade signal may fire twice in rapid succession because of:
    * Network retry on a successful-but-unconfirmed POST
    * Two concurrent threads processing the same webhook
    * A strategy re-evaluating a signal before the first order fills

The solution
------------
Each trade receives a **fingerprint** built from the four attributes that
uniquely identify an intent:

    fingerprint = hash(strategy + symbol + direction + time_bucket)

A ``time_bucket`` divides continuous time into discrete windows (default:
60 seconds).  Within a single window, identical strategy+symbol+direction
triples are considered duplicates.

If the same fingerprint is seen again within ``dedup_window_seconds``, the
second (and subsequent) requests are **rejected** with a clear reason.

Architecture
------------
::

    before placing order:
        result = guard.check_and_register(
            strategy="RSI_9",
            symbol="BTC-USD",
            direction="long",
        )
        if not result.allowed:
            logger.warning("Duplicate trade blocked: %s", result.reason)
            return

    fingerprint = strategy + symbol + direction
    time_bucket = int(time.time() / dedup_window_seconds)

    if fingerprint in recent_fingerprints:
        → reject (DUPLICATE)
    else:
        → accept, register fingerprint with TTL

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

    result = guard.check_and_register(
        strategy="RSI_9",
        symbol="BTC-USD",
        direction="long",
    )
    if not result.allowed:
        return  # duplicate — skip order
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

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("nija.trade_duplication_guard")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DedupResult:
    """Result of a duplicate-check call.

    Attributes
    ----------
    allowed:
        True if the trade is a genuine new request; False if it is a duplicate.
    fingerprint:
        The computed fingerprint string.
    reason:
        Human-readable explanation (populated when ``allowed=False``).
    first_seen_at:
        ISO timestamp of when this fingerprint was first registered (only
        set when ``allowed=False``).
    """
    allowed: bool
    fingerprint: str
    reason: str = ""
    first_seen_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal fingerprint record
# ---------------------------------------------------------------------------

@dataclass
class _FingerprintRecord:
    fingerprint: str
    strategy: str
    symbol: str
    direction: str
    registered_at: float   # monotonic clock
    registered_at_iso: str
    count: int = 1          # how many times we've seen this fingerprint


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TradeDuplicationGuardConfig:
    """Configuration for the Trade Duplication Guard.

    Attributes
    ----------
    dedup_window_seconds:
        Length of the deduplication window in seconds.  Two requests with
        the same strategy+symbol+direction within this window are treated as
        duplicates.
        Default: 60 (one minute).
    cleanup_interval_seconds:
        How often the guard purges expired fingerprints from its registry.
        Default: 300 (5 minutes).
    max_registry_size:
        Hard cap on the number of fingerprints held in memory at once.
        Oldest entries are evicted first when the cap is reached.
        Default: 10_000.
    """
    dedup_window_seconds: float = 60.0
    cleanup_interval_seconds: float = 300.0
    max_registry_size: int = 10_000


# ---------------------------------------------------------------------------
# Main guard
# ---------------------------------------------------------------------------

class TradeDuplicationGuard:
    """Fingerprint-based duplicate trade blocker.

    Thread-safe.  Use ``get_trade_duplication_guard()`` for the singleton.
    """

    def __init__(
        self,
        config: Optional[TradeDuplicationGuardConfig] = None,
    ) -> None:
        self._config = config or TradeDuplicationGuardConfig()
        self._lock = threading.RLock()

        # fingerprint → _FingerprintRecord
        self._registry: Dict[str, _FingerprintRecord] = {}

        # Audit log of blocked trades
        self._blocked_log: List[Dict] = []

        # Stats
        self._total_checked: int = 0
        self._total_blocked: int = 0
        self._total_registered: int = 0

        # Background cleanup thread
        self._stop_cleanup = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="TradeDedupCleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

        logger.info(
            "🛡️  TradeDuplicationGuard initialised | window=%.0fs | max_size=%d",
            self._config.dedup_window_seconds,
            self._config.max_registry_size,
        )

    # ------------------------------------------------------------------
    # Fingerprint helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_fingerprint(
        strategy: str,
        symbol: str,
        direction: str,
        time_bucket: int,
    ) -> str:
        """Build a unique, deterministic fingerprint string.

        The fingerprint encodes all four components.  The ``time_bucket``
        groups continuous time into ``dedup_window_seconds``-wide windows so
        that signals fired at e.g. t=0.1s and t=0.9s within the same window
        map to the same fingerprint, while t=1.1s (next window) does not.
        """
        raw = f"{strategy}|{symbol}|{direction}|{time_bucket}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"{strategy}:{symbol}:{direction}:{time_bucket}:{digest}"

    def _current_time_bucket(self) -> int:
        """Return an integer time bucket index based on the current wall time."""
        return int(time.time() / self._config.dedup_window_seconds)

    # ------------------------------------------------------------------
    # Core dedup API
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
        strategy: str,
        symbol: str,
        direction: str,
        time_bucket: Optional[int] = None,
    ) -> DedupResult:
        """Check for a duplicate and, if unique, register the fingerprint.

        This is the **single entry point** — call it before placing any trade
        order.

        Parameters
        ----------
        strategy:
            Name of the trading strategy (e.g. ``"RSI_9"``).
        symbol:
            Instrument symbol (e.g. ``"BTC-USD"``).
        direction:
            Trade direction: ``"long"`` or ``"short"``.
        time_bucket:
            Override for the time bucket (only used in tests).

        Returns
        -------
        DedupResult
            ``allowed=True``  → trade is unique; proceed.
            ``allowed=False`` → duplicate detected; skip this trade.
        """
        bucket = time_bucket if time_bucket is not None else self._current_time_bucket()
        fp = self._build_fingerprint(strategy, symbol, direction, bucket)

        with self._lock:
            self._total_checked += 1
            now_mono = time.monotonic()

            # Check if fingerprint already in registry and not yet expired
            if fp in self._registry:
                record = self._registry[fp]
                age = now_mono - record.registered_at
                if age <= self._config.dedup_window_seconds:
                    # Duplicate within window
                    record.count += 1
                    self._total_blocked += 1
                    reason = (
                        f"Duplicate trade blocked: strategy={strategy} symbol={symbol} "
                        f"direction={direction} — fingerprint '{fp}' already registered "
                        f"{age:.1f}s ago (window={self._config.dedup_window_seconds:.0f}s)"
                    )
                    logger.warning("🚫 %s", reason)
                    self._blocked_log.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "fingerprint": fp,
                        "strategy": strategy,
                        "symbol": symbol,
                        "direction": direction,
                        "first_seen_at": record.registered_at_iso,
                        "age_seconds": age,
                    })
                    return DedupResult(
                        allowed=False,
                        fingerprint=fp,
                        reason=reason,
                        first_seen_at=record.registered_at_iso,
                    )
                else:
                    # Expired — remove stale record; treat as new
                    del self._registry[fp]

            # Enforce max registry size (evict oldest)
            if len(self._registry) >= self._config.max_registry_size:
                oldest_fp = min(
                    self._registry,
                    key=lambda k: self._registry[k].registered_at,
                )
                del self._registry[oldest_fp]
                logger.debug(
                    "🗑️  Registry full — evicted oldest fingerprint %s", oldest_fp
                )

            # Register new fingerprint
            now_iso = datetime.now(timezone.utc).isoformat()
            self._registry[fp] = _FingerprintRecord(
                fingerprint=fp,
                strategy=strategy,
                symbol=symbol,
                direction=direction,
                registered_at=now_mono,
                registered_at_iso=now_iso,
            )
            self._total_registered += 1

        logger.debug(
            "✅ Trade registered: strategy=%s symbol=%s direction=%s fp=%s",
            strategy,
            symbol,
            direction,
            fp,
        )
        return DedupResult(allowed=True, fingerprint=fp)

    def is_duplicate(
        self,
        strategy: str,
        symbol: str,
        direction: str,
        time_bucket: Optional[int] = None,
    ) -> bool:
        """Return True if the given trade would be a duplicate.

        This is a **read-only** check — it does not register the fingerprint.
        Use ``check_and_register`` for the normal gating flow.
        """
        bucket = time_bucket if time_bucket is not None else self._current_time_bucket()
        fp = self._build_fingerprint(strategy, symbol, direction, bucket)
        now_mono = time.monotonic()
        with self._lock:
            if fp in self._registry:
                age = now_mono - self._registry[fp].registered_at
                return age <= self._config.dedup_window_seconds
        return False

    def clear_fingerprint(
        self,
        strategy: str,
        symbol: str,
        direction: str,
        time_bucket: Optional[int] = None,
    ) -> bool:
        """Manually remove a fingerprint from the registry.

        Useful after a confirmed order failure so the trade can be retried
        in the same time window.

        Returns
        -------
        bool
            True if the fingerprint was found and removed.
        """
        bucket = time_bucket if time_bucket is not None else self._current_time_bucket()
        fp = self._build_fingerprint(strategy, symbol, direction, bucket)
        with self._lock:
            if fp in self._registry:
                del self._registry[fp]
                logger.info("🗑️  Fingerprint cleared: %s", fp)
                return True
        return False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _purge_expired(self) -> int:
        """Remove all expired fingerprints from the registry.

        Returns
        -------
        int
            Number of records removed.
        """
        now_mono = time.monotonic()
        window = self._config.dedup_window_seconds
        with self._lock:
            expired = [
                fp
                for fp, rec in self._registry.items()
                if (now_mono - rec.registered_at) > window
            ]
            for fp in expired:
                del self._registry[fp]
        if expired:
            logger.debug("🗑️  Purged %d expired fingerprint(s)", len(expired))
        return len(expired)

    def _cleanup_loop(self) -> None:
        """Background thread: periodically purge expired records."""
        while not self._stop_cleanup.is_set():
            self._stop_cleanup.wait(self._config.cleanup_interval_seconds)
            if self._stop_cleanup.is_set():
                break
            try:
                self._purge_expired()
            except Exception as exc:
                logger.error("❌ Dedup cleanup error: %s", exc)

    def stop(self) -> None:
        """Stop the background cleanup thread (call on shutdown)."""
        self._stop_cleanup.set()
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Return a JSON-serialisable status snapshot."""
        with self._lock:
            return {
                "registry_size": len(self._registry),
                "total_checked": self._total_checked,
                "total_registered": self._total_registered,
                "total_blocked": self._total_blocked,
                "dedup_window_seconds": self._config.dedup_window_seconds,
                "max_registry_size": self._config.max_registry_size,
                "recent_blocked": self._blocked_log[-10:],
            }

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
    """Return the global ``TradeDuplicationGuard`` singleton.

    Parameters
    ----------
    config:
        Optional configuration; only used on the **first** call.
        Subsequent callers receive the same instance regardless of ``config``.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TradeDuplicationGuard(config)
    return _instance


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

    cfg = TradeDuplicationGuardConfig(dedup_window_seconds=60.0)
    guard = TradeDuplicationGuard(cfg)

    print("\n=== Trade Duplication Guard — smoke test ===\n")

    r1 = guard.check_and_register("RSI_9", "BTC-USD", "long")
    print(f"First attempt  — allowed: {r1.allowed}  fp={r1.fingerprint}")

    r2 = guard.check_and_register("RSI_9", "BTC-USD", "long")
    print(f"Second attempt — allowed: {r2.allowed}  reason={r2.reason[:60]}…")

    # Different direction — should pass
    r3 = guard.check_and_register("RSI_9", "BTC-USD", "short")
    print(f"Short attempt  — allowed: {r3.allowed}")

    # Different strategy — should pass
    r4 = guard.check_and_register("RSI_14", "BTC-USD", "long")
    print(f"RSI_14 attempt — allowed: {r4.allowed}")

    print(f"\nStatus: {guard.get_status()}")

    guard.stop()
    print("\n✅ Smoke test complete")
