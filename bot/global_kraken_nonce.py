"""
NIJA Kraken Nonce Manager
=========================

Single source of truth for all Kraken API nonces.

Rules
─────
✅ ONE singleton (KrakenNonceManager) shared across every thread and every account
✅ Strictly monotonic — never repeats, never decreases
✅ Safe across threads, retries, and container restarts
✅ Thread-safe via a single Lock

Usage
─────
    from bot.global_kraken_nonce import KrakenNonceManager, get_kraken_api_lock

    nonce_manager = KrakenNonceManager()
    payload["nonce"] = nonce_manager.next_nonce()
"""

import logging
import threading
import time

_logger = logging.getLogger(__name__)

# ── API serialisation lock ────────────────────────────────────────────────────
# Kraken rejects parallel private calls on the same API key.
# Acquire this lock around every private Kraken API call.
_KRAKEN_API_LOCK = threading.RLock()


def get_kraken_api_lock() -> threading.RLock:
    """Return the process-wide Kraken API serialisation lock."""
    return _KRAKEN_API_LOCK


# ── Single nonce manager ──────────────────────────────────────────────────────

class KrakenNonceManager:
    """
    Thread-safe, strictly monotonic nonce generator for Kraken.

    Guarantees:
    - Always increasing (never repeats)
    - Safe across threads
    - Safe across retries
    - Works in Railway / container environments

    ONE instance is shared across every thread and every account — there is
    no second nonce source anywhere in the codebase.
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init()
                    cls._instance = instance
        return cls._instance

    def _init(self):
        self._lock = threading.Lock()
        self._last_nonce = int(time.time() * 1000)
        self._consecutive_errors = 0
        self._active_requests = 0

    # ── Core nonce generation ──────────────────────────────────────────────

    def next_nonce(self) -> int:
        """Return the next strictly-increasing millisecond nonce."""
        with self._lock:
            now = int(time.time() * 1000)

            # Enforce strict monotonic increase
            if now <= self._last_nonce:
                self._last_nonce += 1
            else:
                self._last_nonce = now

            return self._last_nonce

    # Alias for backward compatibility with broker_manager.py and others
    def get_nonce(self) -> int:
        """Alias for next_nonce() — backward compatibility."""
        return self.next_nonce()

    def get_last_nonce(self) -> int:
        """Return the last issued nonce without advancing it."""
        with self._lock:
            return self._last_nonce

    def reset_to_safe_value(self, offset_ms: int = 1_000) -> None:
        """Reset nonce to now + offset_ms milliseconds (default 1 s)."""
        with self._lock:
            self._last_nonce = int(time.time() * 1000) + offset_ms

    # ── Active-request tracking ────────────────────────────────────────────

    def begin_request(self) -> None:
        """Call before every Kraken private API request."""
        with self._lock:
            self._active_requests += 1

    def end_request(self) -> None:
        """Call after every Kraken private API request (success or failure)."""
        with self._lock:
            if self._active_requests > 0:
                self._active_requests -= 1

    # ── Error / success tracking ───────────────────────────────────────────

    def record_error(self) -> None:
        """
        Record a Kraken 'invalid nonce' error.

        Increments the consecutive-error counter.  When the counter reaches 3
        AND there are no in-flight requests, the nonce is reset to now + 1 s
        and the counter is cleared.  No reset is performed on errors 1 or 2.
        """
        with self._lock:
            self._consecutive_errors += 1
            if self._consecutive_errors >= 3 and self._active_requests == 0:
                _logger.warning(
                    "KrakenNonceManager: 3 consecutive nonce errors with no active requests "
                    "— resetting nonce to now + 1 s"
                )
                self._last_nonce = int(time.time() * 1000) + 1_000
                self._consecutive_errors = 0

    def record_success(self) -> None:
        """Reset the consecutive-error counter after a successful API call."""
        with self._lock:
            self._consecutive_errors = 0


# ── Backward-compatibility aliases ───────────────────────────────────────────
# broker_manager.py, reset_kraken_nonce.py, and others import these names
# directly.  All route to the one KrakenNonceManager singleton.

NonceManager = KrakenNonceManager
GlobalKrakenNonceManager = KrakenNonceManager

# ── Global singleton (module-level shortcut) ──────────────────────────────────
_nonce_manager = KrakenNonceManager()


def get_kraken_nonce() -> int:
    """Return the next nonce from the shared KrakenNonceManager singleton."""
    return _nonce_manager.next_nonce()


# ── Legacy compatibility shims ────────────────────────────────────────────────
# These names were imported by broker_manager, broker_integration,
# independent_broker_trader, and user_nonce_manager.  Every call routes to
# the one KrakenNonceManager singleton.

def get_global_kraken_nonce() -> int:
    """Return the next nonce from the shared KrakenNonceManager singleton."""
    return _nonce_manager.next_nonce()


def get_global_nonce_manager() -> KrakenNonceManager:
    """Return the KrakenNonceManager singleton (legacy callers expected a manager object)."""
    return _nonce_manager


def get_global_nonce_stats() -> dict:
    """Minimal stats dict for legacy callers."""
    return {"last_nonce": _nonce_manager.get_last_nonce()}


def record_kraken_nonce_error() -> None:
    """Record a nonce error on the shared KrakenNonceManager."""
    _nonce_manager.record_error()


def record_kraken_nonce_success() -> None:
    """Record a successful call — resets the consecutive-error counter."""
    _nonce_manager.record_success()


def reset_global_kraken_nonce() -> None:
    """Startup-only reset — delegates to KrakenNonceManager.reset_to_safe_value()."""
    _nonce_manager.reset_to_safe_value()


def jump_global_kraken_nonce_forward(milliseconds: int) -> None:
    """No-op: forward jumps have been removed in favour of strict monotonic nonces."""


def nonce_reset_triggered_recently(window_s: float = 300.0) -> bool:
    """Always False — reset tracking has been removed."""
    return False


def cleanup_legacy_nonce_files() -> None:
    """No-op shim kept for import compatibility."""


__all__ = [
    "KrakenNonceManager",
    "NonceManager",
    "GlobalKrakenNonceManager",
    "get_kraken_api_lock",
    "get_kraken_nonce",
    "get_global_kraken_nonce",
    "get_global_nonce_manager",
    "get_global_nonce_stats",
    "record_kraken_nonce_error",
    "record_kraken_nonce_success",
    "reset_global_kraken_nonce",
    "jump_global_kraken_nonce_forward",
    "nonce_reset_triggered_recently",
    "cleanup_legacy_nonce_files",
]
