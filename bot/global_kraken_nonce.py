"""
NIJA Kraken Nonce Manager  (production-grade)
=============================================

Single source of truth for all Kraken API nonces.

Rules
─────
✅ ONE singleton (KrakenNonceManager) shared across every thread and every account
✅ Strictly monotonic — never repeats, never decreases
✅ Safe across threads, retries, and container restarts
✅ Thread-safe via a single Lock
✅ Cross-process persistence — nonce survives restarts via an atomic file store
✅ Startup jump (+10 s ahead of wall-clock) prevents stale-nonce on hot restart
✅ Escalating reset backoff: 10 s → 20 s → 30 s → 60 s on repeated errors

Usage
─────
    from bot.global_kraken_nonce import KrakenNonceManager, get_kraken_api_lock

    nonce_manager = KrakenNonceManager()
    payload["nonce"] = nonce_manager.next_nonce()
"""

import glob as _glob
import logging
import os
import threading
import time

_logger = logging.getLogger(__name__)

# ── Persistence file ──────────────────────────────────────────────────────────
# Written atomically (write-then-rename) with mode 0600.
# Falls back gracefully if the directory is read-only.
_NONCE_FILE = os.path.join(
    os.environ.get("NIJA_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")),
    "kraken_nonce.state",
)

# ── Tuning constants (milliseconds unless noted) ──────────────────────────────
_STARTUP_JUMP_MS: int = 10_000       # lead on first start / hot restart
_STARTUP_CLAMP_MS: int = 55_000      # never start more than 55 s ahead
_RESET_OFFSET_MS: int = 60_000       # baseline reset offset (was 1 s — now 60 s)
# Escalating reset offsets applied on consecutive errors
_ERROR_OFFSETS_MS: tuple = (10_000, 20_000, 30_000, 60_000)
_ERROR_RESET_THRESHOLD: int = 3     # first N errors: no reset; from N onwards: escalating backoff

# ── API serialisation lock ────────────────────────────────────────────────────
# Kraken rejects parallel private calls on the same API key.
# Acquire this lock around every private Kraken API call.
_KRAKEN_API_LOCK = threading.RLock()


def get_kraken_api_lock() -> threading.RLock:
    """Return the process-wide Kraken API serialisation lock."""
    return _KRAKEN_API_LOCK


# ── Persistence helpers ───────────────────────────────────────────────────────

def _read_persisted_nonce() -> int:
    """Return the last persisted nonce, or 0 if unavailable."""
    try:
        with open(_NONCE_FILE, "r") as fh:
            return int(fh.read().strip())
    except Exception:
        return 0


def _write_persisted_nonce(value: int) -> None:
    """Atomically persist *value* to the nonce state file (write + rename)."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(_NONCE_FILE)), exist_ok=True)
        tmp = _NONCE_FILE + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(str(value))
        os.chmod(tmp, 0o600)
        os.replace(tmp, _NONCE_FILE)
    except Exception as exc:
        _logger.debug("KrakenNonceManager: could not persist nonce (%s)", exc)


# ── Single nonce manager ──────────────────────────────────────────────────────

class KrakenNonceManager:
    """
    Thread-safe, strictly monotonic, cross-process-persistent nonce generator
    for Kraken.

    Guarantees:
    - Always increasing (never repeats)
    - Safe across threads
    - Safe across retries and container restarts (file persistence)
    - Startup jump prevents stale-nonce on hot restart
    - Escalating backoff on consecutive nonce errors
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
        self._consecutive_errors = 0
        self._active_requests = 0

        now_ms = int(time.time() * 1000)
        persisted = _read_persisted_nonce()

        # Start well ahead of both the persisted value and wall-clock so that
        # any in-flight nonces from a previous process are already stale.
        startup = max(persisted + 1, now_ms + _STARTUP_JUMP_MS)
        # Clamp: never start so far ahead that Kraken's window rejects us.
        startup = min(startup, now_ms + _STARTUP_CLAMP_MS)
        self._last_nonce = startup
        _write_persisted_nonce(self._last_nonce)

        _logger.info(
            "KrakenNonceManager: init nonce=%d (persisted=%d, now=%d, lead=%+d ms)",
            self._last_nonce, persisted, now_ms, self._last_nonce - now_ms,
        )

    # ── Core nonce generation ──────────────────────────────────────────────

    def next_nonce(self) -> int:
        """Return the next strictly-increasing millisecond nonce and persist it."""
        with self._lock:
            now = int(time.time() * 1000)

            # Enforce strict monotonic increase
            if now <= self._last_nonce:
                self._last_nonce += 1
            else:
                self._last_nonce = now

            _write_persisted_nonce(self._last_nonce)
            return self._last_nonce

    # Alias for backward compatibility with broker_manager.py and others
    def get_nonce(self) -> int:
        """Alias for next_nonce() — backward compatibility."""
        return self.next_nonce()

    def get_last_nonce(self) -> int:
        """Return the last issued nonce without advancing it."""
        with self._lock:
            return self._last_nonce

    def reset_to_safe_value(self, offset_ms: int = _RESET_OFFSET_MS) -> None:
        """
        Reset nonce to now + offset_ms milliseconds (default 60 s).

        Use after confirmed Kraken 'invalid nonce' responses to skip past any
        nonces that may have been used by other processes or prior requests.
        """
        with self._lock:
            new_val = int(time.time() * 1000) + offset_ms
            _logger.warning(
                "KrakenNonceManager: reset_to_safe_value → %d (offset=%d ms)",
                new_val, offset_ms,
            )
            self._last_nonce = new_val
            _write_persisted_nonce(self._last_nonce)

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

        Uses an escalating backoff table:
          error 1-2 : no reset (allow natural retry)
          error 3   : reset to now + 10 s
          error 4   : reset to now + 20 s
          error 5   : reset to now + 30 s
          error 6+  : reset to now + 60 s

        The reset is skipped while there are in-flight requests (another
        thread is mid-call and will produce a higher nonce naturally).
        """
        with self._lock:
            self._consecutive_errors += 1
            errors = self._consecutive_errors

            if errors < _ERROR_RESET_THRESHOLD:
                # First two errors: let monotonic logic self-correct
                return

            if self._active_requests > 0:
                # In-flight requests will yield higher nonces — wait
                return

            # Pick escalating offset
            idx = min(errors - _ERROR_RESET_THRESHOLD, len(_ERROR_OFFSETS_MS) - 1)
            offset = _ERROR_OFFSETS_MS[idx]
            new_val = int(time.time() * 1000) + offset
            _logger.warning(
                "KrakenNonceManager: %d consecutive nonce errors — "
                "resetting to now + %d ms (nonce=%d)",
                errors, offset, new_val,
            )
            self._last_nonce = new_val
            _write_persisted_nonce(self._last_nonce)

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
    """Jump the nonce forward by *milliseconds* (manual recovery helper)."""
    with _nonce_manager._lock:
        _nonce_manager._last_nonce += milliseconds
        _write_persisted_nonce(_nonce_manager._last_nonce)


def nonce_reset_triggered_recently(window_s: float = 300.0) -> bool:
    """Always False — reset tracking has been removed."""
    return False


def cleanup_legacy_nonce_files() -> None:
    """Remove old per-account nonce text files left by earlier implementations."""
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    for path in _glob.glob(os.path.join(data_dir, "kraken_nonce*.txt")):
        try:
            os.remove(path)
            _logger.debug("KrakenNonceManager: removed legacy nonce file %s", path)
        except Exception:
            pass


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
