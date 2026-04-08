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
✅ NTP clock check at startup — Kraken requires system clock within ±1 second

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

# fcntl is available on Linux/macOS; skip on Windows
try:
    import fcntl as _fcntl
    _FCNTL_AVAILABLE = True
except ImportError:
    _fcntl = None  # type: ignore[assignment]
    _FCNTL_AVAILABLE = False

_logger = logging.getLogger(__name__)

# ── Persistence file ──────────────────────────────────────────────────────────
_STATE_FILE = os.path.join(
    os.environ.get("NIJA_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")),
    "kraken_nonce.state",
)
_NONCE_FILE = _STATE_FILE  # backward-compat alias

_PERSISTED_PERMISSIONS = 0o600

# ── Module-level lock (shared by all callers) ─────────────────────────────────
_LOCK = threading.Lock()

# ── Nonce tuning constants (milliseconds) ─────────────────────────────────────
_STARTUP_JUMP_MS: int = 10_000      # added to persisted nonce on hot restart
_RESET_OFFSET_MS: int = 60_000      # offset used by reset_to_safe_value()

# ── Nuclear reset / trading-pause constants ───────────────────────────────────
# When consecutive nonce errors exceed this threshold the manager performs a
# "nuclear" reset (30-minute forward jump) and pauses all trading for
# _TRADING_PAUSE_S seconds so Kraken's nonce window can catch up.
_NUCLEAR_RESET_THRESHOLD: int = int(os.environ.get("NIJA_NONCE_NUCLEAR_THRESHOLD", "10"))
_NUCLEAR_RESET_OFFSET_MS: int = 1_800_000   # 30 min — beats any previously stored nonce
_TRADING_PAUSE_S: float = float(os.environ.get("NIJA_NONCE_PAUSE_SECONDS", "60"))
_ERROR_RESET_THRESHOLD: int = 3     # errors < threshold: no jump

# Corruption guard thresholds — if persisted nonce is this far ahead of
# wall-clock the state file is likely corrupted.
_CORRUPTION_WARN_MS: int  =    600_000   # 10 min → warn but keep
_CORRUPTION_RESET_MS: int = 86_400_000   # 24 h   → discard and restart

# ── NTP clock-sync constants ──────────────────────────────────────────────────
# Kraken is EXTREMELY sensitive to clock drift.  Even a few seconds off can
# trigger continuous nonce errors that block ALL accounts.
_NTP_SERVER: str = "pool.ntp.org"
_NTP_TIMEOUT_S: float = 3.0      # UDP query timeout
_NTP_STRICT_OFFSET_S: float = 1.0  # Kraken rejects nonces when |offset| > ~1 s
_NTP_WARN_OFFSET_S: float = 0.5   # warn early so operators act before it breaks

# ── API serialisation lock ────────────────────────────────────────────────────
_KRAKEN_API_LOCK = threading.RLock()


def get_kraken_api_lock() -> threading.RLock:
    """Return the process-wide Kraken API serialisation lock."""
    return _KRAKEN_API_LOCK


# ── NTP helpers (module-level so validate_all_env_vars.py can import them) ────

def check_ntp_sync() -> dict:
    """
    Query pool.ntp.org and return clock-sync results.

    Returns a dict with keys:
      ok        bool   — True when |offset| ≤ _NTP_STRICT_OFFSET_S (±1 s)
      offset_s  float  — system − NTP in seconds (positive = system ahead)
      server    str    — NTP server queried
      error     str    — empty on success; error description on failure
    """
    result = {"ok": False, "offset_s": 0.0, "server": _NTP_SERVER, "error": ""}
    try:
        import ntplib
        client = ntplib.NTPClient()
        response = client.request(_NTP_SERVER, version=3, timeout=_NTP_TIMEOUT_S)
        result["offset_s"] = response.offset
        result["ok"] = abs(response.offset) <= _NTP_STRICT_OFFSET_S
    except ImportError:
        result["error"] = "ntplib not installed — run: pip install ntplib==0.4.0"
    except Exception as exc:
        result["error"] = str(exc)
    return result


def log_ntp_clock_status() -> bool:
    """
    Run an NTP check and log at the appropriate level.

    Returns True when the clock is within Kraken's ±1 s tolerance.
    Logs a clear fix command so operators know exactly what to run.
    """
    r = check_ntp_sync()

    if r["error"]:
        _logger.warning(
            "⚠️  NTP check skipped (%s). "
            "Verify clock manually: sudo ntpdate %s",
            r["error"], _NTP_SERVER,
        )
        return True  # unknown — don't block startup

    offset_ms = r["offset_s"] * 1000
    abs_s = abs(r["offset_s"])

    if not r["ok"]:
        _logger.error(
            "❌ CLOCK DRIFT: system clock is %+.3f s (%+.0f ms) vs NTP (%s). "
            "Kraken requires ±1 s — nonce errors WILL occur on ALL accounts. "
            "Fix NOW: sudo ntpdate %s",
            r["offset_s"], offset_ms, _NTP_SERVER, _NTP_SERVER,
        )
        return False
    elif abs_s > _NTP_WARN_OFFSET_S:
        _logger.warning(
            "⚠️  Clock drift: %+.3f s (%+.0f ms) vs NTP (%s). "
            "Within ±1 s Kraken window but drifting. Recommend: sudo ntpdate %s",
            r["offset_s"], offset_ms, _NTP_SERVER, _NTP_SERVER,
        )
        return True
    else:
        _logger.info(
            "✅ NTP clock OK: %+.3f s vs %s (within Kraken ±1 s tolerance).",
            r["offset_s"], _NTP_SERVER,
        )
        return True


# ── Legacy-file cleanup (must be defined before KrakenNonceManager uses it) ───

def cleanup_legacy_nonce_files() -> None:
    """Remove old per-account nonce .txt files left by earlier implementations."""
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    for path in _glob.glob(os.path.join(data_dir, "kraken_nonce*.txt")):
        try:
            os.remove(path)
            _logger.debug("KrakenNonceManager: removed legacy nonce file %s", path)
        except Exception:
            pass


# ── Nonce manager ─────────────────────────────────────────────────────────────

class KrakenNonceManager:
    """
    Thread-safe, strictly monotonic, cross-process-persistent nonce generator
    for Kraken.

    Guarantees:
    - Always increasing (never repeats or decreases)
    - Safe across threads
    - Safe across retries and container restarts (file persistence)
    - Startup jump prevents stale-nonce on hot restart
    - Escalating jump backoff on consecutive nonce errors
    - NTP clock checked at startup — Kraken requires ±1 s accuracy

    ONE instance is shared across every thread and every account.
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

    def _init(self) -> None:
        self._error_count = 0
        self._trading_paused_until: float = 0.0   # epoch seconds; 0 = not paused
        os.makedirs(os.path.dirname(os.path.abspath(_STATE_FILE)), exist_ok=True)
        cleanup_legacy_nonce_files()

        # NTP check first — clock drift is the #1 cause of Kraken nonce errors.
        # Kraken is extremely sensitive: even a few seconds off triggers
        # continuous "EAPI:Invalid nonce" errors that block ALL accounts.
        log_ntp_clock_status()

        self._last_nonce = self._load_last_nonce()
        self._persist()
        lead_ms = self._last_nonce - int(time.time() * 1000)
        _logger.info(
            "KrakenNonceManager: ready — nonce=%d  lead=%+d ms",
            self._last_nonce, lead_ms,
        )

    # ── Core ──────────────────────────────────────────────────────────────

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
        Advance nonce to at least now + offset_ms (default 60 s).

        Only ever *increases* the nonce — never decreases it.  Safe to call
        proactively from connect() without risking a Kraken rejection.
        """
        with _LOCK:
            floor = int(time.time() * 1000) + offset_ms
            if floor > self._last_nonce:
                _logger.warning(
                    "KrakenNonceManager: reset_to_safe_value → %d  (was=%d  offset=%d ms)",
                    floor, self._last_nonce, offset_ms,
                )
                self._last_nonce = floor
                self._persist()
            else:
                _logger.debug(
                    "KrakenNonceManager: reset_to_safe_value skipped — "
                    "nonce already ahead (nonce=%d  floor=%d  lead=%+d ms)",
                    self._last_nonce, floor,
                    self._last_nonce - int(time.time() * 1000),
                )

    # ── Backward-compat no-ops ────────────────────────────────────────────

    def begin_request(self) -> None:
        pass

    def end_request(self) -> None:
        pass

    def is_paused(self) -> bool:
        """Return True when trading is paused after a nuclear nonce reset."""
        with _LOCK:
            return time.time() < self._trading_paused_until

    def get_pause_remaining(self) -> float:
        """Return seconds remaining in the trading pause (0.0 when not paused)."""
        with _LOCK:
            remaining = self._trading_paused_until - time.time()
            return max(0.0, remaining)

    # ── Error / success tracking ──────────────────────────────────────────

    def record_error(self) -> None:
        """
        Record a Kraken 'EAPI:Invalid nonce' error with escalating backoff.

          errors 1–2 : no jump (allow natural monotonic retry)
          error  3   : jump +10 s
          error  4   : jump +20 s
          error  5   : jump +30 s
          error  6+  : jump +60 s

        When the consecutive error count reaches _NUCLEAR_RESET_THRESHOLD
        a nuclear reset (+30 min) is applied and trading is paused for
        _TRADING_PAUSE_S seconds so Kraken's nonce window can recover.

        Counter resets only on record_success().
        """
        with _LOCK:
            self._error_count += 1

            # Nuclear reset after too many consecutive failures
            if self._error_count >= _NUCLEAR_RESET_THRESHOLD:
                floor = int(time.time() * 1000) + _NUCLEAR_RESET_OFFSET_MS
                # Always increase — never decrease a runaway nonce
                new_nonce = max(floor, self._last_nonce + 1)
                _logger.error(
                    "🚨 KrakenNonceManager: NUCLEAR RESET after %d consecutive errors — "
                    "nonce → +30 min floor (%d → %d) and pausing trading for %.0f s",
                    self._error_count, self._last_nonce, new_nonce, _TRADING_PAUSE_S,
                )
                self._last_nonce = new_nonce
                self._persist()
                self._trading_paused_until = time.time() + _TRADING_PAUSE_S
                self._error_count = 0   # reset so escalation can start fresh
                return

            jump = self._backoff_ms(self._error_count)
            if jump > 0:
                self._last_nonce += jump
                self._persist()
                _logger.warning(
                    "KrakenNonceManager: nonce error #%d — jumped +%d ms  nonce=%d",
                    self._error_count, jump, self._last_nonce,
                )

    def record_success(self) -> None:
        """Reset the consecutive-error counter after a successful API call.

        Also clears any active trading pause so that connected user accounts
        resume immediately once the platform Kraken nonce issue is resolved,
        rather than waiting for the full pause timer to expire.
        """
        with _LOCK:
            self._error_count = 0
            if self._trading_paused_until > 0.0:
                _logger.info(
                    "✅ KrakenNonceManager: trading pause cleared on successful API call"
                )
                self._trading_paused_until = 0.0

    # ── Private helpers ───────────────────────────────────────────────────

    def _load_last_nonce(self) -> int:
        """
        Compute the startup nonce from persisted state and wall-clock.

        Key design decision: we do NOT clamp the result to a maximum lead.
        The old _STARTUP_CLAMP_MS=55 s clamp silently *decreased* the nonce
        whenever error-recovery backoffs had pushed it beyond 45 s ahead,
        causing Kraken to reject the very first call after a restart.
        Kraken's nonce rule is purely monotonic — no documented upper bound.
        """
        now_ms = int(time.time() * 1000)
        persisted = 0
        try:
            with open(_STATE_FILE) as fh:
                persisted = int(fh.read().strip())
        except (FileNotFoundError, ValueError):
            pass

        lead_ms = persisted - now_ms
        if lead_ms > _CORRUPTION_RESET_MS:
            _logger.error(
                "KrakenNonceManager: persisted nonce is %d ms (%.1f h) ahead — "
                "likely corrupted; resetting. Run reset_kraken_nonce.py to fix.",
                lead_ms, lead_ms / 3_600_000,
            )
            persisted = 0
        elif lead_ms > _CORRUPTION_WARN_MS:
            _logger.warning(
                "KrakenNonceManager: persisted nonce is %d ms (%.1f min) ahead — "
                "system clock may have drifted backward.  Check NTP sync.",
                lead_ms, lead_ms / 60_000,
            )

        # Always advance beyond persisted AND ensure minimum lead from wall-clock.
        return max(persisted + _STARTUP_JUMP_MS, now_ms + _STARTUP_JUMP_MS)

    def _persist(self) -> None:
        """Atomically write nonce to disk (write-then-rename, mode 0600).

        Uses an exclusive advisory lock (fcntl.LOCK_EX) on the .tmp file so
        that two processes can never interleave their writes — even if the
        process lock in bot.py is bypassed.
        """
        try:
            tmp = _STATE_FILE + ".tmp"
            with open(tmp, "w") as fh:
                if _FCNTL_AVAILABLE:
                    _fcntl.flock(fh, _fcntl.LOCK_EX)
                fh.write(str(self._last_nonce))
                if _FCNTL_AVAILABLE:
                    _fcntl.flock(fh, _fcntl.LOCK_UN)
            os.chmod(tmp, _PERSISTED_PERMISSIONS)
            os.replace(tmp, _STATE_FILE)
        except Exception as exc:
            _logger.debug("KrakenNonceManager: persist failed (%s)", exc)

    def _backoff_ms(self, error_count: int) -> int:
        if error_count <= 2:
            return 0
        if error_count == 3:
            return 10_000
        if error_count == 4:
            return 20_000
        if error_count == 5:
            return 30_000
        return 60_000  # 6+


# ── Backward-compatibility aliases ────────────────────────────────────────────
NonceManager = KrakenNonceManager
GlobalKrakenNonceManager = KrakenNonceManager

# ── Module-level singleton ────────────────────────────────────────────────────
_nonce_manager = KrakenNonceManager()


# ── Public shortcuts ──────────────────────────────────────────────────────────

def get_kraken_nonce() -> int:
    return _nonce_manager.next_nonce()


def get_global_kraken_nonce() -> int:
    return _nonce_manager.next_nonce()


def get_global_nonce_manager() -> KrakenNonceManager:
    return _nonce_manager


def get_global_nonce_stats() -> dict:
    return {"last_nonce": _nonce_manager.get_last_nonce()}


def record_kraken_nonce_error() -> None:
    _nonce_manager.record_error()


def record_kraken_nonce_success() -> None:
    _nonce_manager.record_success()


def reset_global_kraken_nonce() -> None:
    _nonce_manager.reset_to_safe_value()


def jump_global_kraken_nonce_forward(milliseconds: int) -> None:
    _nonce_manager.jump_forward(milliseconds)


def nonce_reset_triggered_recently(window_s: float = 300.0) -> bool:
    return False  # tracking removed; retained for compatibility


def is_nonce_trading_paused() -> bool:
    """Return True when a nuclear nonce reset has triggered a trading pause."""
    return _nonce_manager.is_paused()


def get_nonce_pause_remaining() -> float:
    """Return seconds remaining in the nonce-triggered trading pause (0.0 when clear)."""
    return _nonce_manager.get_pause_remaining()


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
    "is_nonce_trading_paused",
    "get_nonce_pause_remaining",
    "cleanup_legacy_nonce_files",
    "check_ntp_sync",
    "log_ntp_clock_status",
]
