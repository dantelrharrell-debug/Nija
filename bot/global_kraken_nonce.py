"""
NIJA Kraken Nonce Manager
=========================

Single source of truth for all Kraken API nonces.

Rules
─────
✅ ONE singleton (NonceManager) shared across every thread and every account
✅ Strictly monotonic — never decreases, never jumps unpredictably
✅ No drift fixing, no adaptive jumps, no retry math
✅ Thread-safe via a single Lock

Usage
─────
    from bot.global_kraken_nonce import NonceManager, get_kraken_api_lock

    nonce_manager = NonceManager()
    payload["nonce"] = nonce_manager.get_nonce()
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

class NonceManager:
    """
    Thread-safe singleton nonce generator for Kraken API.

    Uses millisecond timestamps (13 digits) with a strict monotonic guarantee:
    if wall-clock time has not advanced since the last call the counter is
    incremented by 1, so every returned value is unique and ordered.

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
        self._nonce = int(time.time() * 1000)

    def get_nonce(self) -> int:
        """Return the next strictly-increasing millisecond nonce."""
        with self._lock:
            now = int(time.time() * 1000)
            if now <= self._nonce:
                self._nonce += 1
            else:
                self._nonce = now
            return self._nonce

    def reset_to_safe_value(self, offset_ms: int = 1_000) -> None:
        """Reset nonce to now + offset_ms milliseconds (default 1 s, startup only)."""
        with self._lock:
            self._nonce = int(time.time() * 1000) + offset_ms


# ── Legacy compatibility shims ────────────────────────────────────────────────
# These names were imported by broker_manager, broker_integration,
# independent_broker_trader, and user_nonce_manager.  They are kept so those
# files do not raise ImportError, but ALL forward-jump behaviour has been
# removed.  Every call routes to the one NonceManager singleton.

def get_global_kraken_nonce() -> int:
    """Return the next nonce from the shared NonceManager singleton."""
    return NonceManager().get_nonce()


# Alias used across several files
get_kraken_nonce = get_global_kraken_nonce


def get_global_nonce_manager():
    """Return the NonceManager singleton (legacy callers expected a manager object)."""
    return NonceManager()


def get_global_nonce_stats() -> dict:
    """Minimal stats dict for legacy callers."""
    return {"last_nonce": NonceManager().get_nonce()}


def record_kraken_nonce_error() -> None:
    """No-op: forward jumps have been removed (FIX 1)."""


def record_kraken_nonce_success() -> None:
    """No-op: escalation counter has been removed."""


def reset_global_kraken_nonce() -> None:
    """Startup-only reset — delegates to NonceManager.reset_to_safe_value()."""
    NonceManager().reset_to_safe_value()


def jump_global_kraken_nonce_forward(milliseconds: int) -> None:
    """No-op: all forward jumps have been removed (FIX 1)."""


def nonce_reset_triggered_recently(window_s: float = 300.0) -> bool:
    """Always False — reset tracking has been removed."""
    return False


def cleanup_legacy_nonce_files() -> None:
    """No-op shim kept for import compatibility."""


__all__ = [
    "NonceManager",
    "get_kraken_api_lock",
    "get_global_kraken_nonce",
    "get_kraken_nonce",
    "get_global_nonce_manager",
    "get_global_nonce_stats",
    "record_kraken_nonce_error",
    "record_kraken_nonce_success",
    "reset_global_kraken_nonce",
    "jump_global_kraken_nonce_forward",
    "nonce_reset_triggered_recently",
    "cleanup_legacy_nonce_files",
]
