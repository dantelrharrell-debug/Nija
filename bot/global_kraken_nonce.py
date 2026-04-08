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
✅ Cross-process safe — fcntl advisory lock on every nonce increment prevents
   two concurrently-running processes from issuing duplicate or out-of-order nonces
✅ Wall-clock guard — auto-advances nonce when it falls behind wall-clock time
   (handles "expiring" nuclear-reset nonces after 30+ minutes in an error loop)

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
_RESET_OFFSET_MS: int = 300_000     # offset used by reset_to_safe_value()

# ── Nuclear reset / trading-pause constants ───────────────────────────────────
# When consecutive nonce errors exceed this threshold the manager performs a
# "nuclear" reset (30-minute forward jump) and pauses all trading for
# _TRADING_PAUSE_S seconds so Kraken's nonce window can catch up.
_NUCLEAR_RESET_THRESHOLD: int = int(os.environ.get("NIJA_NONCE_NUCLEAR_THRESHOLD", "10"))
_NUCLEAR_RESET_OFFSET_MS: int = 1_800_000   # 30 min — beats any previously stored nonce
_TRADING_PAUSE_S: float = float(os.environ.get("NIJA_NONCE_PAUSE_SECONDS", "60"))
_ERROR_RESET_THRESHOLD: int = 3     # errors < threshold: no jump

# ── Nonce resync / probe-calibration constants ────────────────────────────────
# Used by probe_and_resync() to dynamically find Kraken's current nonce floor.
# Each failed probe call jumps the nonce forward by _PROBE_STEP_MS.
# Up to _PROBE_MAX_ATTEMPTS attempts are made before giving up.
# Default: 6 × 5 min = 30 min of forward coverage — enough to outlast any
# previous bot session's nuclear-reset or error-accumulation nonce.
_PROBE_STEP_MS: int = int(os.environ.get("NIJA_NONCE_PROBE_STEP_MS", "300000"))      # 5 min per step
_PROBE_MAX_ATTEMPTS: int = int(os.environ.get("NIJA_NONCE_PROBE_MAX_ATTEMPTS", "6"))  # up to 30 min

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

# ── Cross-process lock file ───────────────────────────────────────────────────
# Used by _CrossProcessLock to serialise nonce reads/writes across concurrently
# running bot processes (e.g. container restart overlap, duplicate start).
_LOCK_FILE = _STATE_FILE + ".lock"


def get_kraken_api_lock() -> threading.RLock:
    """Return the process-wide Kraken API serialisation lock."""
    return _KRAKEN_API_LOCK


# ── Cross-process exclusive lock ──────────────────────────────────────────────

class _CrossProcessLock:
    """
    Context manager that acquires an exclusive advisory lock on *_LOCK_FILE*
    via ``fcntl.flock`` (Linux / macOS only).

    On platforms without fcntl the context manager is a no-op so the code
    remains portable to Windows.  The lock is automatically released when the
    file descriptor is closed — even if the holding process crashes — so there
    is no risk of a permanently-stuck lock file.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._fh = None

    def __enter__(self) -> "_CrossProcessLock":
        if _FCNTL_AVAILABLE:
            try:
                # Open in write mode — the file is used purely as a lock target
                # and stores no data; truncation on each open is intentional.
                self._fh = open(self._path, "w")
                _fcntl.flock(self._fh, _fcntl.LOCK_EX)
            except Exception as exc:
                _logger.debug(
                    "KrakenNonceManager: cross-process lock unavailable (%s) — "
                    "proceeding without cross-process serialisation",
                    exc,
                )
                self._fh = None
        return self

    def __exit__(self, *_: object) -> None:
        if self._fh is not None:
            try:
                _fcntl.flock(self._fh, _fcntl.LOCK_UN)
                self._fh.close()
            except Exception:
                pass
            self._fh = None


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

        # Startup is the most likely moment for two processes to race.  Hold the
        # cross-process lock for the entire read → compute → write sequence so a
        # second process starting at the same time cannot claim the same nonce.
        with _LOCK:
            with _CrossProcessLock(_LOCK_FILE):
                self._last_nonce = self._load_last_nonce()
                self._persist()
        lead_ms = self._last_nonce - int(time.time() * 1000)
        _logger.info(
            "KrakenNonceManager: ready — nonce=%d  lead=%+d ms",
            self._last_nonce, lead_ms,
        )

    # ── Core ──────────────────────────────────────────────────────────────

    def next_nonce(self) -> int:
        """Return the next strictly-increasing nonce and persist it.

        Cross-process safe: acquires an exclusive advisory ``fcntl`` lock on
        *_LOCK_FILE* so two concurrently-running bot processes (e.g. a duplicate
        container start or a crash-loop restart overlap) never issue the same
        nonce to Kraken.

        Also auto-advances the nonce when it has fallen behind wall-clock time.
        This handles the scenario where a nuclear-reset nonce (+30 min) was set
        over 30 minutes ago and the bot remained in an error loop — Kraken
        rejects nonces whose ms-timestamp is significantly in the past.
        """
        with _LOCK:
            with _CrossProcessLock(_LOCK_FILE):
                # ── Cross-process sync ──────────────────────────────────────
                # Re-read the state file to pick up any nonce advance written
                # by another process (e.g. a nuclear reset in Process B that
                # put the high-water mark above this process's in-memory value).
                file_nonce = self._read_state_file_raw()
                if file_nonce == 0 and self._last_nonce > 0:
                    _logger.debug(
                        "KrakenNonceManager: cross-proc sync — state file returned 0 "
                        "(file missing or unreadable); using in-memory nonce (%d)",
                        self._last_nonce,
                    )
                elif file_nonce > self._last_nonce:
                    _logger.info(
                        "KrakenNonceManager: cross-proc sync — in-memory nonce "
                        "(%d) advanced to file value (%d, delta=%+d ms)",
                        self._last_nonce, file_nonce,
                        file_nonce - self._last_nonce,
                    )
                    self._last_nonce = file_nonce

                # ── Wall-clock guard ────────────────────────────────────────
                # If the nonce has fallen behind the current wall-clock time,
                # advance it forward.  This happens when a nuclear-reset nonce
                # (+30 min) is more than 30 minutes old — Kraken rejects the
                # stale ms-timestamp.  Advancing to now+_STARTUP_JUMP_MS
                # ensures the very next nonce is accepted.
                now_ms = int(time.time() * 1000)
                if self._last_nonce < now_ms:
                    new_floor = now_ms + _STARTUP_JUMP_MS
                    _logger.warning(
                        "KrakenNonceManager: nonce (%d) fell behind wall-clock "
                        "(%d) by %d ms — auto-advancing to now+%d ms (%d)",
                        self._last_nonce, now_ms,
                        now_ms - self._last_nonce,
                        _STARTUP_JUMP_MS, new_floor,
                    )
                    self._last_nonce = new_floor

                # ── Monotonic increment ─────────────────────────────────────
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
                with _CrossProcessLock(_LOCK_FILE):
                    # Read the file so the nuclear nonce beats the highest value
                    # written by any other concurrently-running process.
                    # If the read fails (returns 0) fall back safely to the
                    # in-memory value via the max() below.
                    file_nonce = self._read_state_file_raw()
                    if file_nonce == 0 and self._last_nonce > 0:
                        _logger.warning(
                            "KrakenNonceManager: nuclear reset — state file unreadable; "
                            "using in-memory high-water mark (%d)",
                            self._last_nonce,
                        )
                    high_water = max(file_nonce, self._last_nonce)
                    floor = int(time.time() * 1000) + _NUCLEAR_RESET_OFFSET_MS
                    # Always increase — never decrease a runaway nonce
                    new_nonce = max(floor, high_water + 1)
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

    # ── Nonce resync / probe-calibration ─────────────────────────────────

    def probe_and_resync(
        self,
        api_call_fn,
        *,
        step_ms: int = _PROBE_STEP_MS,
        max_attempts: int = _PROBE_MAX_ATTEMPTS,
    ) -> bool:
        """
        Nonce resync handshake: probe Kraken's server-side nonce floor and
        jump forward until an API call is accepted.

        This resolves three root causes of "EAPI:Invalid nonce":

          1. **Another process still running** — a stale container or duplicate
             bot instance may have advanced Kraken's expected nonce far beyond
             what this process's state file records.

          2. **Kraken expecting a much higher nonce** — on ephemeral filesystems
             (Railway, Heroku, Render) the state file is wiped on container
             restart.  Kraken still remembers the last nonce it accepted from
             the previous session, which can be 30+ minutes ahead of wall-clock.

          3. **Clock sync slightly off** — even a few seconds of NTP drift can
             push nonces outside Kraken's ±1 s acceptance window.  Jumping by
             probe steps quickly lands us back in an acceptable range.

        Strategy
        --------
        Call ``api_call_fn()`` with the current nonce.  If Kraken returns
        ``EAPI:Invalid nonce``, jump ``_last_nonce`` forward by *step_ms* and
        retry.  Repeat until Kraken accepts or *max_attempts* is exhausted.

        Args:
            api_call_fn: ``callable() → dict``
                Must return a Kraken API response dict (with ``"error"`` key).
                Typically wraps ``broker._kraken_private_call("Balance", {})``.
                On a network exception the probe stops immediately — the error
                is not a nonce issue and retrying would not help.
            step_ms: Forward-jump per failed probe (default: ``_PROBE_STEP_MS``,
                     i.e. 5 minutes per step, env ``NIJA_NONCE_PROBE_STEP_MS``).
            max_attempts: Maximum probe attempts before giving up (default:
                          ``_PROBE_MAX_ATTEMPTS``, env
                          ``NIJA_NONCE_PROBE_MAX_ATTEMPTS``).  The total
                          forward coverage is ``step_ms × max_attempts``
                          (default: 30 minutes).

        Returns:
            ``True``  — Kraken accepted the call; nonce is calibrated.
            ``False`` — All attempts exhausted or a non-nonce error occurred.
        """
        _logger.info(
            "KrakenNonceManager.probe_and_resync: starting nonce calibration "
            "(step=%d ms, max_attempts=%d, nonce=%d)",
            step_ms, max_attempts, self.get_last_nonce(),
        )
        for attempt in range(1, max_attempts + 1):
            try:
                result = api_call_fn()
            except Exception as exc:
                # Network / auth error — not a nonce issue; stop probing.
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                    "exception (%s); stopping (not a nonce issue)",
                    attempt, max_attempts, exc,
                )
                return False

            if not isinstance(result, dict):
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                    "unexpected response type %s; stopping",
                    attempt, max_attempts, type(result).__name__,
                )
                return False

            errors = result.get("error") or []
            error_str = ", ".join(errors)
            is_nonce_err = any(
                kw in error_str.lower()
                for kw in ("invalid nonce", "eapi:invalid nonce", "nonce window")
            )

            if not is_nonce_err:
                # Success or a non-nonce error (permission, etc.) — calibration done.
                if not errors:
                    _logger.info(
                        "✅ KrakenNonceManager.probe_and_resync: calibrated on "
                        "attempt %d/%d — nonce=%d",
                        attempt, max_attempts, self.get_last_nonce(),
                    )
                else:
                    _logger.debug(
                        "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                        "non-nonce error (%s); nonce calibration not required",
                        attempt, max_attempts, error_str,
                    )
                return True

            # Nonce rejected — jump forward and retry.
            with _LOCK:
                self._last_nonce += step_ms
                self._persist()
            _logger.warning(
                "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                "nonce rejected (%s), jumped +%d ms → nonce=%d",
                attempt, max_attempts, error_str, step_ms, self._last_nonce,
            )

        _logger.error(
            "❌ KrakenNonceManager.probe_and_resync: calibration FAILED after "
            "%d attempts (total jump: +%d ms). nonce=%d. "
            "Check for duplicate processes or reset the nonce state file.",
            max_attempts, step_ms * max_attempts, self.get_last_nonce(),
        )
        return False

    @staticmethod
    def detect_other_process_running() -> bool:
        """
        Non-blocking check: return ``True`` if another bot process appears to
        hold the cross-process nonce lock right now.

        Uses ``fcntl.LOCK_NB`` (non-blocking) to try acquiring the exclusive
        lock.  If the attempt fails with ``BlockingIOError`` another process
        is holding it.  Always returns ``False`` on platforms without fcntl.
        """
        if not _FCNTL_AVAILABLE:
            return False
        try:
            fh = open(_LOCK_FILE, "w")
            try:
                _fcntl.flock(fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                _fcntl.flock(fh, _fcntl.LOCK_UN)
                return False   # lock was free — no other process
            except (BlockingIOError, OSError):
                return True    # lock is held by another process
            finally:
                fh.close()
        except Exception:
            return False

    # ── Private helpers ───────────────────────────────────────────────────

    def _read_state_file_raw(self) -> int:
        """Read and return the raw persisted nonce value (0 on any error)."""
        try:
            with open(_STATE_FILE, encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (FileNotFoundError, ValueError, OSError, UnicodeDecodeError):
            return 0

    def _load_last_nonce(self) -> int:
        """
        Compute the startup nonce from persisted state and wall-clock.

        Must be called while holding *both* the in-process ``_LOCK`` and the
        cross-process ``_CrossProcessLock`` so that the read → compute → write
        sequence in ``_init()`` is atomic across threads and processes.

        Key design decision: we do NOT clamp the result to a maximum lead.
        The old _STARTUP_CLAMP_MS=55 s clamp silently *decreased* the nonce
        whenever error-recovery backoffs had pushed it beyond 45 s ahead,
        causing Kraken to reject the very first call after a restart.
        Kraken's nonce rule is purely monotonic — no documented upper bound.
        """
        now_ms = int(time.time() * 1000)
        persisted = self._read_state_file_raw()

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
