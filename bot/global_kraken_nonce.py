"""
NIJA Kraken Nonce Manager  (production-grade)
=============================================

Single source of truth for all Kraken API nonces.

Rules
─────
✅ ONE singleton (KrakenNonceManager) shared across every thread and every account
✅ Strictly monotonic — never repeats, never decreases
✅ Safe across threads, retries, and container restarts
✅ Thread-safe via a module-level Lock
✅ Cross-process persistence — nonce survives restarts via an atomic file store
✅ Startup jump (+10 s ahead of wall-clock) prevents stale-nonce on hot restart
✅ Escalating jump backoff on repeated errors
✅ Manual jump control via jump_forward()

Usage
─────
    from bot.global_kraken_nonce import get_kraken_nonce

    nonce = get_kraken_nonce()
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
_STATE_FILE = os.path.join(
    os.environ.get("NIJA_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")),
    "kraken_nonce.state",
)
# Keep _NONCE_FILE as an alias so any code that imported it directly still works.
_NONCE_FILE = _STATE_FILE

_PERSISTED_PERMISSIONS = 0o600

# ── Module-level lock (shared by all callers) ─────────────────────────────────
_LOCK = threading.Lock()

# ── Tuning constants (milliseconds) ──────────────────────────────────────────
_STARTUP_JUMP_MS: int = 10_000      # lead added to persisted nonce on hot restart
_RESET_OFFSET_MS: int = 60_000      # offset used by reset_to_safe_value()
_ERROR_RESET_THRESHOLD: int = 3     # errors < threshold: no jump; at threshold: apply backoff
# Corruption guard: if persisted nonce is more than this far ahead of wall-clock,
# it is likely corrupted (e.g. the file was written from a future date or by a bug).
_CORRUPTION_WARN_MS: int  = 600_000    # 10 minutes — warn but keep value
_CORRUPTION_RESET_MS: int = 86_400_000 # 24 hours  — reset to safe value (clear corruption)

# ── API serialisation lock ────────────────────────────────────────────────────
# Kraken rejects parallel private calls on the same API key.
# Acquire this lock around every private Kraken API call.
_KRAKEN_API_LOCK = threading.RLock()


def get_kraken_api_lock() -> threading.RLock:
    """Return the process-wide Kraken API serialisation lock."""
    return _KRAKEN_API_LOCK


# ── NTP clock-sync constants ──────────────────────────────────────────────────
_NTP_SERVER: str = "pool.ntp.org"
_NTP_TIMEOUT_S: float = 3.0          # query timeout — must be fast on startup
_NTP_STRICT_OFFSET_S: float = 1.0    # Kraken requires clock within ±1 second
_NTP_WARN_OFFSET_S: float = 0.5      # warn earlier so operators act before it's critical


def check_ntp_sync() -> dict:
    """
    Query pool.ntp.org and return a dict with clock-sync results.

    Returns
    -------
    dict with keys:
      ok          bool   — True if offset is within ±_NTP_STRICT_OFFSET_S
      offset_s    float  — signed offset: system − NTP (positive = system ahead)
      server      str    — NTP server used
      error       str    — empty string on success, error description on failure
    """
    result = {"ok": False, "offset_s": 0.0, "server": _NTP_SERVER, "error": ""}
    try:
        import ntplib  # optional dep — graceful fallback if missing
        client = ntplib.NTPClient()
        response = client.request(_NTP_SERVER, version=3, timeout=_NTP_TIMEOUT_S)
        offset = response.offset  # seconds, positive means system clock is AHEAD
        result["offset_s"] = offset
        result["ok"] = abs(offset) <= _NTP_STRICT_OFFSET_S
    except ImportError:
        result["error"] = "ntplib not installed — skipping NTP check"
    except Exception as exc:
        result["error"] = str(exc)
    return result


def log_ntp_clock_status() -> bool:
    """
    Run an NTP check and log the result at the appropriate level.

    Returns True if the clock is within the ±1 s Kraken tolerance, False otherwise.
    Logs a clear remediation message so operators know exactly what to run.
    """
    r = check_ntp_sync()

    if r["error"]:
        _logger.warning(
            "⚠️  NTP clock check skipped (%s).  "
            "Ensure system clock is synced: sudo ntpdate %s",
            r["error"], _NTP_SERVER,
        )
        return True  # unknown — don't block startup, but warn

    offset_ms = r["offset_s"] * 1000
    abs_offset_s = abs(r["offset_s"])

    if not r["ok"]:
        # Clock is off by more than ±1 s — Kraken will reject nonces
        _logger.error(
            "❌ CLOCK DRIFT DETECTED: system clock is %+.3f s (%+.0f ms) vs NTP (%s). "
            "Kraken requires ±1 s accuracy — nonce errors WILL occur.  "
            "Fix: sudo ntpdate %s  (or enable chrony/timesyncd).",
            r["offset_s"], offset_ms, _NTP_SERVER, _NTP_SERVER,
        )
        return False
    elif abs_offset_s > _NTP_WARN_OFFSET_S:
        # Within tolerance but getting close — warn early
        _logger.warning(
            "⚠️  Clock drift: system is %+.3f s (%+.0f ms) vs NTP (%s). "
            "Still within Kraken's ±1 s window, but monitor closely.  "
            "Recommend: sudo ntpdate %s",
            r["offset_s"], offset_ms, _NTP_SERVER, _NTP_SERVER,
        )
        return True
    else:
        _logger.info(
            "✅ NTP clock OK: offset %+.3f s vs %s (Kraken ±1 s tolerance met).",
            r["offset_s"], _NTP_SERVER,
        )
        return True



    """
    Thread-safe, strictly monotonic, cross-process-persistent nonce generator
    for Kraken.

    Guarantees:
    - Always increasing (never repeats)
    - Safe across threads
    - Safe across retries and container restarts (file persistence)
    - Startup jump prevents stale-nonce on hot restart
    - Escalating jump backoff on consecutive nonce errors
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
        self._error_count = 0
        os.makedirs(os.path.dirname(os.path.abspath(_STATE_FILE)), exist_ok=True)
        cleanup_legacy_nonce_files()
        self._last_nonce = self._load_last_nonce()
        self._persist()
        lead_ms = self._last_nonce - int(time.time() * 1000)
        _logger.info(
            "KrakenNonceManager: init nonce=%d (lead=%+d ms)",
            self._last_nonce, lead_ms,
        )
        self._log_clock_health(lead_ms)

    # ── Core nonce generation ──────────────────────────────────────────────

    def next_nonce(self) -> int:
        """Return the next strictly-increasing nonce and persist it."""
        with _LOCK:
            self._last_nonce += 1
            self._persist()
            return self._last_nonce

    def get_nonce(self) -> int:
        """Alias for next_nonce() — backward compatibility."""
        return self.next_nonce()

    def get_last_nonce(self) -> int:
        """Return the last issued nonce without advancing it."""
        with _LOCK:
            return self._last_nonce

    def jump_forward(self, ms: int) -> None:
        """Manually advance nonce by *ms* milliseconds."""
        with _LOCK:
            self._last_nonce += ms
            self._persist()

    def reset_to_safe_value(self, offset_ms: int = _RESET_OFFSET_MS) -> None:
        """
        Advance nonce to at least now + offset_ms milliseconds (default 60 s).

        This method only ever *increases* the nonce — it will never decrease
        it below the current value, so it is safe to call proactively from
        connect() without risking a Kraken "invalid nonce" rejection.

        Use after confirmed Kraken 'invalid nonce' responses to skip past any
        nonces that may have been used by other processes or prior requests.
        """
        with _LOCK:
            floor = int(time.time() * 1000) + offset_ms
            if floor > self._last_nonce:
                _logger.warning(
                    "KrakenNonceManager: reset_to_safe_value → %d (offset=%d ms, was=%d)",
                    floor, offset_ms, self._last_nonce,
                )
                self._last_nonce = floor
                self._persist()
            else:
                _logger.debug(
                    "KrakenNonceManager: reset_to_safe_value skipped — already ahead "
                    "(nonce=%d, floor=%d, lead=%+d ms)",
                    self._last_nonce, floor, self._last_nonce - int(time.time() * 1000),
                )

    # ── Active-request tracking (no-ops — retained for backward compatibility) ──

    def begin_request(self) -> None:
        """No-op — retained for backward compatibility."""
        pass

    def end_request(self) -> None:
        """No-op — retained for backward compatibility."""
        pass

    # ── Error / success tracking ───────────────────────────────────────────

    def record_error(self) -> None:
        """
        Record a Kraken 'invalid nonce' error with escalating jump backoff.

        Uses a cumulative forward-jump table:
          errors 1–2  : no jump (allow natural monotonic retry)
          error  3    : jump nonce forward +10 s
          error  4    : jump nonce forward +20 s
          error  5    : jump nonce forward +30 s
          error  6+   : jump nonce forward +60 s

        Counter resets to zero only on record_success().
        """
        with _LOCK:
            self._error_count += 1
            jump = self._calculate_backoff(self._error_count)
            if jump > 0:
                self._last_nonce += jump
                self._persist()
                _logger.warning(
                    "KrakenNonceManager: nonce error #%d — jumped forward %d ms (nonce=%d)",
                    self._error_count, jump, self._last_nonce,
                )

    def record_success(self) -> None:
        """Reset the error counter after a successful API call."""
        with _LOCK:
            self._error_count = 0

    # ── Private helpers ────────────────────────────────────────────────────

    def _log_clock_health(self, lead_ms: int) -> None:
        """Log a clock-health diagnostic at startup to help operators detect NTP issues."""
        import datetime as _dt
        utc_now = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        if lead_ms < 0:
            # Nonce is BEHIND wall-clock — possible after a large forward NTP correction
            _logger.warning(
                "KrakenNonceManager: startup nonce is %d ms BEHIND wall-clock (%s). "
                "This can happen if the system clock jumped forward (NTP step). "
                "The bot will auto-recover via next_nonce(), but verify NTP sync.",
                abs(lead_ms), utc_now,
            )
        elif lead_ms > _CORRUPTION_WARN_MS:
            _logger.warning(
                "KrakenNonceManager: startup nonce lead is %d ms (%.1f min) — "
                "system clock: %s.  Large lead is normal after error-recovery but "
                "verify NTP sync if Kraken nonce errors persist.",
                lead_ms, lead_ms / 60_000, utc_now,
            )
        else:
            _logger.debug(
                "KrakenNonceManager: clock health OK — system clock: %s, "
                "nonce lead: %+d ms",
                utc_now, lead_ms,
            )

    def _load_last_nonce(self) -> int:
        """Compute startup nonce from persisted state and wall-clock."""
        now_ms = int(time.time() * 1000)
        persisted = 0
        try:
            with open(_STATE_FILE, "r") as fh:
                persisted = int(fh.read().strip())
        except (FileNotFoundError, ValueError):
            pass

        # Corruption guard: if persisted is unreasonably far in the future it
        # probably means the state file was corrupted (e.g. written with bad
        # data or from a system with a severely wrong clock).
        lead_ms = persisted - now_ms
        if lead_ms > _CORRUPTION_RESET_MS:
            _logger.error(
                "KrakenNonceManager: persisted nonce is %d ms (%.1f h) ahead of "
                "wall-clock — likely corrupted, resetting to safe value.",
                lead_ms, lead_ms / 3_600_000,
            )
            persisted = 0  # treat as fresh start; reset to now + jump
        elif lead_ms > _CORRUPTION_WARN_MS:
            _logger.warning(
                "KrakenNonceManager: persisted nonce is %d ms (%.1f min) ahead of "
                "wall-clock — system clock may have drifted backward or the nonce "
                "accumulated large error-recovery jumps.  Recommend NTP sync.",
                lead_ms, lead_ms / 60_000,
            )

        # Always advance at least _STARTUP_JUMP_MS beyond the persisted value so
        # we skip past any nonces that Kraken already received in the previous
        # session.  Also ensure we are at least _STARTUP_JUMP_MS ahead of the
        # current wall-clock.
        #
        # NOTE: We intentionally do NOT clamp the result to a "maximum lead"
        # here.  The old _STARTUP_CLAMP_MS=55 s clamp would silently DECREASE
        # the nonce whenever error-recovery backoffs had pushed it beyond 45 s
        # ahead, causing Kraken to reject the very next call after a restart.
        # Kraken's nonce contract is purely monotonic — there is no documented
        # upper-bound on how far ahead a nonce may be.
        start_nonce = max(persisted + _STARTUP_JUMP_MS, now_ms + _STARTUP_JUMP_MS)
        return start_nonce

    def _persist(self) -> None:
        """Persist nonce atomically to disk (write-then-rename, chmod 0600)."""
        try:
            tmp_file = _STATE_FILE + ".tmp"
            with open(tmp_file, "w") as fh:
                fh.write(str(self._last_nonce))
            os.chmod(tmp_file, _PERSISTED_PERMISSIONS)
            os.replace(tmp_file, _STATE_FILE)
        except Exception as exc:
            _logger.debug("KrakenNonceManager: could not persist nonce (%s)", exc)

    def _calculate_backoff(self, error_count: int) -> int:
        """Return the forward-jump (ms) for the given consecutive error count."""
        if error_count <= 2:
            return 0
        elif error_count == 3:
            return 10_000
        elif error_count == 4:
            return 20_000
        elif error_count == 5:
            return 30_000
        else:  # 6+
            return 60_000


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
    _nonce_manager.jump_forward(milliseconds)


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
