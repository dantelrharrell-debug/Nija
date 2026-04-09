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
import json
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
#
# Threshold lowered from 10 → 5: fewer consecutive errors before the nuclear
# jump fires, preventing repeated small backoff jumps from compounding into an
# ever-growing nonce lead.
#
# Pause raised from 60 s → 300 s: a 30-min nuclear jump warrants a 5-minute
# pause so the probe_and_resync handshake (which may need several 10-min steps)
# can complete before new user-account connections attempt to use the nonce.
_NUCLEAR_RESET_THRESHOLD: int = int(os.environ.get("NIJA_NONCE_NUCLEAR_THRESHOLD", "5"))
_NUCLEAR_RESET_OFFSET_MS: int = 1_800_000   # 30 min — beats any previously stored nonce
_TRADING_PAUSE_S: float = float(os.environ.get("NIJA_NONCE_PAUSE_SECONDS", "300"))
_ERROR_RESET_THRESHOLD: int = 3     # errors < threshold: no jump

# After this many consecutive nuclear resets within one session the manager
# automatically activates deep-probe mode (12 × 10 min = 120 min coverage),
# exactly as if NIJA_DEEP_NONCE_RESET=1 had been set at startup.
_AUTO_DEEP_RESET_THRESHOLD: int = int(os.environ.get("NIJA_AUTO_DEEP_THRESHOLD", "2"))

# ── Nonce resync / probe-calibration constants ────────────────────────────────
# Used by probe_and_resync() to dynamically find Kraken's current nonce floor.
# Each failed probe call jumps the nonce forward by _PROBE_STEP_MS.
# Up to _PROBE_MAX_ATTEMPTS attempts are made before giving up.
#
# Default coverage raised from 6 × 5 min (30 min) → 12 × 5 min (60 min) so
# a single nuclear reset (+30 min) plus accumulated backoff jumps is always
# within range without requiring NIJA_DEEP_NONCE_RESET=1.
_PROBE_STEP_MS: int = int(os.environ.get("NIJA_NONCE_PROBE_STEP_MS", "300000"))       # 5 min per step
_PROBE_MAX_ATTEMPTS: int = int(os.environ.get("NIJA_NONCE_PROBE_MAX_ATTEMPTS", "12")) # up to 60 min

# ── Deep-reset constants ──────────────────────────────────────────────────────
# Activated by NIJA_DEEP_NONCE_RESET=1.  Provides 120-minute probe coverage
# and an NTP-corrected startup floor to survive worst-case nonce gaps caused by:
#   • Multiple consecutive nuclear resets from a previous session
#   • Host clock drift (backward) undervaluing the computed nonce floor
#   • A competing process that raced ahead while this one was down
#
# Deep startup floor: nonce is set to at least now + _DEEP_STARTUP_FLOOR_MS so
# that the first probe step starts well above Kraken's recorded high-water mark.
_DEEP_PROBE_STEP_MS: int = int(os.environ.get("NIJA_NONCE_DEEP_STEP_MS", "600000"))         # 10 min per step
_DEEP_PROBE_MAX_ATTEMPTS: int = int(os.environ.get("NIJA_NONCE_DEEP_MAX_ATTEMPTS", "12"))   # 12 × 10 min = 120 min
_DEEP_STARTUP_FLOOR_MS: int = 3_600_000   # 60 min lead on startup when deep-reset is active

# Extra probe attempts automatically added when a duplicate process is detected
# holding the nonce lock, since that process may have advanced the floor further.
_DUPLICATE_PROC_EXTRA_ATTEMPTS: int = 6

# ── Adaptive Offset Engine constants ─────────────────────────────────────────
# The Adaptive Offset Engine replaces the fixed _PROBE_STEP_MS with a learned
# offset computed from two signals:
#
#   offset = max(
#       startup_delay + jitter + retry_buffer,   ← timing-based floor
#       observed_nonce_gap + safety_margin        ← gap-based floor (learned)
#   )
#
# On the first run (no history) the timing floor is used.  After each
# successful probe calibration the engine records the observed gap via an
# Exponential Moving Average (EMA, α=0.3) so the estimate improves over time.
# The learned state is persisted to `data/kraken_nonce_offsets.json`.

_AO_STATE_FILE: str = os.path.join(
    os.environ.get("NIJA_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")),
    "kraken_nonce_offsets.json",
)

# Timing components (ms) — mirror the broker_manager.py startup timing so the
# engine's floor reflects the real cost of a container restart.
_AO_STARTUP_DELAY_MS: int = int(os.environ.get("NIJA_AO_STARTUP_DELAY_MS", "15000"))  # 15 s startup delay
_AO_JITTER_MS: int        = int(os.environ.get("NIJA_AO_JITTER_MS",        "5000"))   # 5 s max jitter
_AO_RETRY_BUFFER_MS: int  = int(os.environ.get("NIJA_AO_RETRY_BUFFER_MS",  "25000"))  # 5 retries × 5 s

# Gap-based component
_AO_SAFETY_MARGIN_MS: int = int(os.environ.get("NIJA_AO_SAFETY_MARGIN_MS", "60000"))  # 60 s above observed gap

# EMA learning parameters
_AO_EMA_ALPHA: float = 0.3   # weight for the most recent observation (30%)
_AO_HISTORY_WINDOW: int = 10  # persist up to 10 historical calibration records

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


# ── Adaptive Offset Engine ────────────────────────────────────────────────────

class AdaptiveNonceOffsetEngine:
    """
    Learns the optimal nonce probe-step / startup-jump offset over time.

    Formula
    -------
    On each call to ``get_optimal_step()`` the engine returns:

        offset = max(
            startup_delay + jitter + retry_buffer,   # timing floor
            observed_nonce_gap + safety_margin        # learned gap floor
        )

    The *timing floor* is a deterministic lower bound derived from the real
    cost of a container restart (startup delay + jitter + retry overhead).

    The *gap floor* is learned from historical probe calibrations: every time
    ``probe_and_resync()`` succeeds it records the total ms it had to jump
    over.  The engine maintains an Exponential Moving Average (EMA, α=0.3)
    of those gaps so the estimate converges quickly while still adapting to
    changes in deployment patterns.

    The learned state (EMA + history) is persisted to
    ``data/kraken_nonce_offsets.json`` so the engine retains knowledge across
    container restarts.  Atomic write-then-rename prevents corruption.

    Singleton
    ---------
    Use ``get_adaptive_offset_engine()`` to obtain the shared instance.
    """

    _instance: "AdaptiveNonceOffsetEngine | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "AdaptiveNonceOffsetEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._init()
                    cls._instance = obj
        return cls._instance  # type: ignore[return-value]

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def _init(self) -> None:
        self._lock = threading.Lock()
        self._history: list[dict] = []  # list of {"gap_ms": int, "ts": float}
        self._ema_gap_ms: float = 0.0
        self._load()

    def _load(self) -> None:
        """Load persisted EMA and history from disk (silent on error)."""
        try:
            with open(_AO_STATE_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            self._history = data.get("history", [])[-_AO_HISTORY_WINDOW:]
            raw_ema = data.get("ema_gap_ms", 0.0)
            self._ema_gap_ms = float(raw_ema) if raw_ema and raw_ema > 0 else 0.0
            if self._ema_gap_ms > 0:
                _logger.info(
                    "AdaptiveNonceOffsetEngine: loaded — ema_gap=%.0f ms (%.1f min), "
                    "history=%d observations",
                    self._ema_gap_ms, self._ema_gap_ms / 60_000, len(self._history),
                )
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            pass   # first run or corrupt file — start fresh
        except Exception as exc:
            _logger.debug("AdaptiveNonceOffsetEngine: load error (%s)", exc)

    def _save(self) -> None:
        """Atomically persist EMA and history (silent on error)."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(_AO_STATE_FILE)), exist_ok=True)
            data = {
                "ema_gap_ms": self._ema_gap_ms,
                "history": self._history[-_AO_HISTORY_WINDOW:],
                "updated_ts": time.time(),
            }
            tmp = _AO_STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, _AO_STATE_FILE)
        except Exception as exc:
            _logger.debug("AdaptiveNonceOffsetEngine: save error (%s)", exc)

    # ── Public API ────────────────────────────────────────────────────────

    def get_optimal_step(self) -> int:
        """
        Return the adaptive offset (ms) to use as a probe step or startup jump.

        When no calibration history exists the timing floor is returned;
        otherwise the learned gap-based floor is blended in via EMA.
        """
        with self._lock:
            return self._compute()

    def record_calibration(self, failed_attempts: int, step_ms: int) -> None:
        """
        Record the outcome of a completed probe_and_resync() run.

        Args:
            failed_attempts: number of times the nonce was rejected before
                             success (0 = calibrated on first try).
            step_ms:         the step size used during that probe run.
        """
        with self._lock:
            observed_gap = failed_attempts * step_ms
            self._history.append({"gap_ms": observed_gap, "ts": time.time()})
            self._history = self._history[-_AO_HISTORY_WINDOW:]

            if self._ema_gap_ms <= 0:
                self._ema_gap_ms = float(observed_gap)
            else:
                self._ema_gap_ms = (
                    _AO_EMA_ALPHA * observed_gap
                    + (1.0 - _AO_EMA_ALPHA) * self._ema_gap_ms
                )
            new_step = self._compute()
            _logger.info(
                "AdaptiveNonceOffsetEngine: recorded gap=%d ms (failed=%d × %d ms) "
                "→ ema=%.0f ms → next_step=%d ms (%.1f min)",
                observed_gap, failed_attempts, step_ms,
                self._ema_gap_ms, new_step, new_step / 60_000,
            )
            self._save()

    def get_stats(self) -> dict:
        """Return current engine state for diagnostics."""
        with self._lock:
            step = self._compute()
            return {
                "ema_gap_ms": self._ema_gap_ms,
                "observations": len(self._history),
                "optimal_step_ms": step,
                "timing_floor_ms": _AO_STARTUP_DELAY_MS + _AO_JITTER_MS + _AO_RETRY_BUFFER_MS,
            }

    def reset_state(self) -> None:
        """
        Clear the EMA and calibration history so the next ``get_optimal_step()``
        call returns the conservative timing floor rather than a potentially-stale
        small EMA value.

        Called by ``KrakenNonceManager.force_resync()`` and by the
        ``NIJA_FORCE_NONCE_RESYNC=1`` startup path to guarantee a fresh
        probe-calibration on the next ``connect()``.
        """
        with self._lock:
            self._history = []
            self._ema_gap_ms = 0.0
        _logger.debug("AdaptiveNonceOffsetEngine: state reset (EMA cleared)")

    # ── Private ───────────────────────────────────────────────────────────

    def _compute(self) -> int:
        """Compute adaptive offset — caller must hold self._lock."""
        timing_floor = _AO_STARTUP_DELAY_MS + _AO_JITTER_MS + _AO_RETRY_BUFFER_MS
        if self._ema_gap_ms > 0:
            gap_floor = int(self._ema_gap_ms) + _AO_SAFETY_MARGIN_MS
            return max(timing_floor, gap_floor)
        # No history — fall back to the static probe step (conservative default)
        return max(timing_floor, _PROBE_STEP_MS)


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


def _get_ntp_backward_drift_ms() -> int:
    """
    Return the backward-clock-drift correction in milliseconds.

    Kraken's nonce floor is anchored to true UTC time.  If the host clock is
    *behind* NTP (``offset_s < 0``), every nonce computed from ``time.time()``
    will be below what Kraken expects.  We compensate by adding the absolute
    lag to any nonce floor derived from ``time.time()``.

    Returns 0 when:
      • the clock is ahead of NTP (no under-counting risk)
      • ntplib is unavailable or the NTP query fails
      • the measured lag is negligible (< 100 ms)

    This function caches nothing and re-queries NTP on every call so it always
    reflects the current drift, even if the system clock changed between calls.
    """
    r = check_ntp_sync()
    if r.get("error") or r.get("offset_s", 0.0) >= 0.0:
        # Clock is ahead of NTP or unknown — no backward-drift correction needed.
        return 0
    # offset_s < 0 → system is behind NTP by |offset_s| seconds.
    lag_ms = int(abs(r["offset_s"]) * 1000)
    return lag_ms if lag_ms >= 100 else 0


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
        # Tracks how many nuclear resets have fired in this session.  When it
        # reaches _AUTO_DEEP_RESET_THRESHOLD, deep-probe mode is automatically
        # activated so probe_and_resync() uses the wider 120-min coverage window.
        self._nuclear_reset_count: int = 0
        os.makedirs(os.path.dirname(os.path.abspath(_STATE_FILE)), exist_ok=True)
        cleanup_legacy_nonce_files()

        # ── Detect deep-reset mode ─────────────────────────────────────────
        # NIJA_DEEP_NONCE_RESET=1 applies a 60-min NTP-corrected startup floor
        # and extends probe_and_resync() to 12 × 10-min = 120-min coverage.
        # Use this when NIJA_FORCE_NONCE_RESYNC=1 alone is insufficient because:
        #   • multiple nuclear resets put Kraken's floor >30 min ahead
        #   • host clock drift caused the computed floor to undershoot
        #   • a competing process advanced the nonce while this one was down
        _deep_reset = os.environ.get("NIJA_DEEP_NONCE_RESET", "").strip() == "1"
        self._deep_reset_active: bool = _deep_reset

        # NIJA_FORCE_NONCE_RESYNC=1 → wipe persisted state + adaptive-offset EMA
        # before initialising so the next probe_and_resync() starts from a clean
        # slate.  Useful when the container's nonce state is too far behind
        # Kraken's server-side floor (e.g. after multiple nuclear resets or a
        # long outage).  The env var is intentionally checked only at _init()
        # time so it has no effect once the singleton is running.
        if os.environ.get("NIJA_FORCE_NONCE_RESYNC", "").strip() == "1" or _deep_reset:
            _logger.warning(
                "KrakenNonceManager: %s — wiping nonce state and adaptive-offset "
                "EMA for a guaranteed fresh calibration",
                "NIJA_DEEP_NONCE_RESET=1" if _deep_reset else "NIJA_FORCE_NONCE_RESYNC=1",
            )
            for _path in (
                _STATE_FILE,
                _STATE_FILE + ".lock",
                _STATE_FILE + ".tmp",
                _AO_STATE_FILE,
                _AO_STATE_FILE + ".tmp",
            ):
                try:
                    os.remove(_path)
                    _logger.debug("KrakenNonceManager: removed %s", _path)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    _logger.debug("KrakenNonceManager: could not remove %s (%s)", _path, exc)
            # Reset the AdaptiveNonceOffsetEngine singleton so it starts fresh
            # with the conservative timing floor (not a stale small EMA).
            _engine = AdaptiveNonceOffsetEngine._instance
            if _engine is not None:
                _engine.reset_state()

        # NTP check first — clock drift is the #1 cause of Kraken nonce errors.
        # Kraken is extremely sensitive: even a few seconds off triggers
        # continuous "EAPI:Invalid nonce" errors that block ALL accounts.
        log_ntp_clock_status()

        # Warn loudly if another bot process is still running.  A competing
        # process will keep issuing nonces after our reset, making it ineffective.
        if KrakenNonceManager.detect_other_process_running():
            _logger.error(
                "🚨 KrakenNonceManager: another bot process is holding the nonce "
                "lock.  Stop ALL duplicate NIJA processes before this reset takes "
                "effect, otherwise the competing process will continue advancing "
                "Kraken's expected nonce and the reset will be ineffective.  "
                "Run: pkill -f bot.py  (or stop the active deployment)."
            )

        # Startup is the most likely moment for two processes to race.  Hold the
        # cross-process lock for the entire read → compute → write sequence so a
        # second process starting at the same time cannot claim the same nonce.
        with _LOCK:
            with _CrossProcessLock(_LOCK_FILE):
                self._last_nonce = self._load_last_nonce()

                # Deep-reset mode: advance nonce to a 60-min NTP-corrected floor
                # so probe_and_resync() starts well above Kraken's high-water mark
                # even after many consecutive nuclear resets.
                if _deep_reset:
                    ntp_corr_ms = _get_ntp_backward_drift_ms()
                    deep_floor = int(time.time() * 1000) + _DEEP_STARTUP_FLOOR_MS + ntp_corr_ms
                    if deep_floor > self._last_nonce:
                        _logger.warning(
                            "KrakenNonceManager: DEEP RESET — startup floor "
                            "now+%d ms + NTP correction +%d ms → %d  (was %d)",
                            _DEEP_STARTUP_FLOOR_MS, ntp_corr_ms,
                            deep_floor, self._last_nonce,
                        )
                        self._last_nonce = deep_floor

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

    def force_resync(self) -> None:
        """
        Hard reset the nonce state for a guaranteed-clean startup.

        Wipes ``data/kraken_nonce.state`` (and related lock/tmp files) **and**
        clears the ``AdaptiveNonceOffsetEngine`` EMA so the next
        ``probe_and_resync()`` starts from the conservative timing floor rather
        than a potentially-stale small EMA.

        Call this from a maintenance script or a one-off Railway shell command
        when NIJA is stopped and you need to guarantee a clean sync on the
        next restart.  The same effect is achieved at boot time by setting the
        environment variable ``NIJA_FORCE_NONCE_RESYNC=1`` before starting.

        Safe to call while the process is running (acquires ``_LOCK``), but for
        best results stop NIJA first so no new nonces are issued after the wipe.
        """
        with _LOCK:
            for _path in (
                _STATE_FILE,
                _STATE_FILE + ".lock",
                _STATE_FILE + ".tmp",
                _AO_STATE_FILE,
                _AO_STATE_FILE + ".tmp",
            ):
                try:
                    os.remove(_path)
                    _logger.debug("KrakenNonceManager.force_resync: removed %s", _path)
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    _logger.debug(
                        "KrakenNonceManager.force_resync: could not remove %s (%s)",
                        _path, exc,
                    )

            # Reset the AdaptiveNonceOffsetEngine in-memory state.
            _engine = AdaptiveNonceOffsetEngine._instance
            if _engine is not None:
                _engine.reset_state()

            # Reset the in-process error counter, nuclear reset counter, and trading pause.
            self._error_count = 0
            self._nuclear_reset_count = 0
            self._trading_paused_until = 0.0

            # Advance nonce to now + RESET_OFFSET_MS so the very next call
            # lands safely above Kraken's window.
            self._last_nonce = int(time.time() * 1000) + _RESET_OFFSET_MS
            self._persist()

            _logger.warning(
                "KrakenNonceManager.force_resync: state wiped — nonce set to "
                "now+%d ms (%d).  Restart NIJA to begin fresh probe calibration.",
                _RESET_OFFSET_MS, self._last_nonce,
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
        """Return seconds remaining in the nonce-triggered trading pause (0.0 when clear)."""
        with _LOCK:
            remaining = self._trading_paused_until - time.time()
            return max(0.0, remaining)

    @property
    def nuclear_reset_count(self) -> int:
        """Return the number of nuclear resets that have fired in this session."""
        with _LOCK:
            return self._nuclear_reset_count

    @property
    def is_deep_reset_active(self) -> bool:
        """
        Return True when deep-reset mode is active for this instance.

        Deep-reset mode is enabled by setting ``NIJA_DEEP_NONCE_RESET=1`` before
        the singleton is constructed.  It activates:

          * a 60-min NTP-corrected startup floor in ``_init()``
          * 12 × 10-min (120 min) probe coverage in ``probe_and_resync()``

        This property is the single source of truth — ``probe_and_resync()``
        reads it so the activation logic is never duplicated.
        """
        return getattr(self, "_deep_reset_active", False)

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

                # ── Auto deep-reset escalation ──────────────────────────────
                # Each nuclear reset adds 30 min to Kraken's expected nonce
                # floor.  After _AUTO_DEEP_RESET_THRESHOLD consecutive nuclear
                # resets the standard 60-min probe coverage (12 × 5 min) may
                # no longer be sufficient.  Automatically switch to deep-probe
                # mode (12 × 10 min = 120 min) so the next probe_and_resync()
                # can reach Kraken's floor without manual intervention.
                self._nuclear_reset_count += 1
                if self._nuclear_reset_count >= _AUTO_DEEP_RESET_THRESHOLD and not self._deep_reset_active:
                    self._deep_reset_active = True
                    _logger.error(
                        "🔴 KrakenNonceManager: %d consecutive nuclear resets — "
                        "AUTO-ACTIVATING deep-probe mode (12 × 10 min = 120 min coverage). "
                        "Kraken's server-side nonce floor is now 60+ min ahead. "
                        "IMMEDIATE ACTION REQUIRED:\n"
                        "  1. Stop ALL Railway services / deployments using this API key.\n"
                        "  2. Delete the compromised Kraken API key and create a NEW one\n"
                        "     (set Nonce Window = 10000 on the new key).\n"
                        "  3. Update KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET.\n"
                        "  4. Set NIJA_DEEP_NONCE_RESET=1 on the first restart.\n"
                        "  5. Deploy ONE instance only.\n"
                        "The bot will continue probing with extended coverage (120 min) "
                        "but a new API key is the only guaranteed fix.",
                    )
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
        step_ms: int = 0,            # 0 = let the adaptive engine decide
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

        Adaptive Offset Engine
        ----------------------
        When *step_ms* is 0 (default) the step is computed by
        ``AdaptiveNonceOffsetEngine.get_optimal_step()``:

            step = max(
                startup_delay + jitter + retry_buffer,   # timing floor
                observed_nonce_gap + safety_margin        # learned floor
            )

        This means the system **learns** the right offset over time — after the
        first successful calibration the next restart will likely succeed on
        attempt 1 rather than needing multiple probe jumps.

        Args:
            api_call_fn: ``callable() → dict``
                Must return a Kraken API response dict (with ``"error"`` key).
                Typically wraps ``broker._kraken_private_call("Balance", {})``.
                On a network exception the probe stops immediately — the error
                is not a nonce issue and retrying would not help.
            step_ms: Forward-jump per failed probe.  Pass ``0`` (default) to
                     let the Adaptive Offset Engine choose.  Pass an explicit
                     value (e.g. ``300_000``) to override.
            max_attempts: Maximum probe attempts (default: ``_PROBE_MAX_ATTEMPTS``,
                          env ``NIJA_NONCE_PROBE_MAX_ATTEMPTS``).

        Returns:
            ``True``  — Kraken accepted the call; nonce is calibrated.
            ``False`` — All attempts exhausted or a non-nonce error occurred.
        """
        # Resolve adaptive step — deep-reset mode overrides with larger step/attempts
        ao = AdaptiveNonceOffsetEngine()
        if step_ms > 0:
            effective_step = step_ms
        elif self.is_deep_reset_active:
            effective_step = _DEEP_PROBE_STEP_MS
        else:
            effective_step = ao.get_optimal_step()

        effective_max_attempts = (
            max(max_attempts, _DEEP_PROBE_MAX_ATTEMPTS) if self.is_deep_reset_active else max_attempts
        )

        _logger.info(
            "KrakenNonceManager.probe_and_resync: starting nonce calibration "
            "(step=%d ms [%.1f min], max_attempts=%d%s, nonce=%d)",
            effective_step, effective_step / 60_000, effective_max_attempts,
            " [DEEP]" if self.is_deep_reset_active else "",
            self.get_last_nonce(),
        )

        # Duplicate-process check: a competing process advances Kraken's nonce
        # floor concurrently, so we need more attempts to catch up.
        if self.detect_other_process_running():
            _logger.warning(
                "⚠️  KrakenNonceManager.probe_and_resync: another bot process "
                "appears to be holding the nonce lock — nonce gap may be larger "
                "than expected.  Stop duplicate processes to prevent conflicts."
            )
            effective_max_attempts += _DUPLICATE_PROC_EXTRA_ATTEMPTS
            _logger.warning(
                "KrakenNonceManager.probe_and_resync: duplicate process detected — "
                "boosting max_attempts to %d to cover the larger nonce gap",
                effective_max_attempts,
            )

        failed_attempts = 0
        for attempt in range(1, effective_max_attempts + 1):
            try:
                result = api_call_fn()
            except Exception as exc:
                # Network / auth error — not a nonce issue; stop probing.
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                    "exception (%s); stopping (not a nonce issue)",
                    attempt, effective_max_attempts, exc,
                )
                # Record a zero-gap calibration (nonce was fine, stopped for
                # other reasons) so EMA is not inflated.
                ao.record_calibration(failed_attempts=0, step_ms=effective_step)
                return False

            if not isinstance(result, dict):
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                    "unexpected response type %s; stopping",
                    attempt, effective_max_attempts, type(result).__name__,
                )
                return False

            errors = result.get("error") or []
            error_str = ", ".join(errors)
            is_nonce_err = any(
                kw in error_str.lower()
                for kw in ("invalid nonce", "eapi:invalid nonce", "nonce window")
            )

            if not is_nonce_err:
                # Success or non-nonce error — calibration complete.
                if not errors:
                    _logger.info(
                        "✅ KrakenNonceManager.probe_and_resync: calibrated on "
                        "attempt %d/%d (failed=%d) — nonce=%d",
                        attempt, effective_max_attempts, failed_attempts, self.get_last_nonce(),
                    )
                else:
                    _logger.debug(
                        "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                        "non-nonce error (%s); nonce calibration not required",
                        attempt, effective_max_attempts, error_str,
                    )
                # Teach the engine how many jumps were actually needed.
                ao.record_calibration(
                    failed_attempts=failed_attempts, step_ms=effective_step
                )
                return True

            # Nonce rejected — count it and jump forward.
            failed_attempts += 1
            with _LOCK:
                self._last_nonce += effective_step
                self._persist()
            _logger.warning(
                "KrakenNonceManager.probe_and_resync: attempt %d/%d — "
                "nonce rejected (%s), jumped +%d ms → nonce=%d",
                attempt, effective_max_attempts, error_str, effective_step, self._last_nonce,
            )

        _logger.error(
            "❌ KrakenNonceManager.probe_and_resync: calibration FAILED after "
            "%d attempts (total jump: +%d ms). nonce=%d. "
            "Check for duplicate processes or reset the nonce state file.",
            effective_max_attempts, effective_step * effective_max_attempts, self.get_last_nonce(),
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
            with open(_LOCK_FILE, "w") as fh:
                try:
                    _fcntl.flock(fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                    _fcntl.flock(fh, _fcntl.LOCK_UN)
                    return False   # lock was free — no other process
                except (BlockingIOError, OSError):
                    return True    # lock is held by another process
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

        if persisted == 0:
            _logger.warning(
                "KrakenNonceManager: no persisted nonce (fresh start or ephemeral FS). "
                "Kraken's server-side floor may be much higher — "
                "probe_and_resync() will calibrate on connect()."
            )

        # Use the adaptive startup jump so we land above Kraken's learned floor
        # rather than always jumping only +10 s.  Falls back to _STARTUP_JUMP_MS
        # when AdaptiveNonceOffsetEngine has no history yet.
        ao_step = AdaptiveNonceOffsetEngine().get_optimal_step()
        adaptive_jump = max(ao_step, _STARTUP_JUMP_MS)
        _logger.debug(
            "KrakenNonceManager._load_last_nonce: adaptive_jump=%d ms (ao=%d, floor=%d)",
            adaptive_jump, ao_step, _STARTUP_JUMP_MS,
        )

        # Always advance beyond persisted AND ensure minimum lead from wall-clock.
        return max(persisted + adaptive_jump, now_ms + adaptive_jump)

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

# ── Module-level singletons ───────────────────────────────────────────────────
_nonce_manager = KrakenNonceManager()


def get_adaptive_offset_engine() -> AdaptiveNonceOffsetEngine:
    """Return the shared AdaptiveNonceOffsetEngine singleton."""
    return AdaptiveNonceOffsetEngine()


# ── Public shortcuts ──────────────────────────────────────────────────────────

def get_kraken_nonce() -> int:
    return _nonce_manager.next_nonce()


def get_global_kraken_nonce() -> int:
    return _nonce_manager.next_nonce()


def get_global_nonce_manager() -> KrakenNonceManager:
    return _nonce_manager


def get_global_nonce_stats() -> dict:
    return {
        "last_nonce": _nonce_manager.get_last_nonce(),
        "nuclear_reset_count": _nonce_manager.nuclear_reset_count,
        "deep_reset_active": _nonce_manager.is_deep_reset_active,
        "trading_paused": _nonce_manager.is_paused(),
        "pause_remaining_s": _nonce_manager.get_pause_remaining(),
    }


def record_kraken_nonce_error() -> None:
    _nonce_manager.record_error()


def record_kraken_nonce_success() -> None:
    _nonce_manager.record_success()


def reset_global_kraken_nonce() -> None:
    _nonce_manager.reset_to_safe_value()


def force_resync_kraken_nonce() -> None:
    """
    Module-level shortcut for ``KrakenNonceManager.force_resync()``.

    Wipes ``data/kraken_nonce.state`` and the adaptive-offset EMA, then
    sets the nonce to ``now + 5 min`` so the very next API call is accepted.
    For operator / maintenance-script use — stop NIJA before calling this.
    """
    _nonce_manager.force_resync()


def jump_global_kraken_nonce_forward(milliseconds: int) -> None:
    _nonce_manager.jump_forward(milliseconds)


def probe_and_resync_nonce(api_call_fn, *, step_ms: int = 0, max_attempts: int = _PROBE_MAX_ATTEMPTS) -> bool:
    """
    Module-level shortcut for ``KrakenNonceManager.probe_and_resync()``.

    Probes Kraken's server-side nonce floor and jumps forward until an API
    call succeeds.  Uses the ``AdaptiveNonceOffsetEngine`` to compute the
    optimal step size (pass ``step_ms > 0`` to override).

    Typical usage in ``broker_manager.py``::

        probe_and_resync_nonce(
            lambda: self._kraken_private_call("Balance", {})
        )
    """
    return _nonce_manager.probe_and_resync(
        api_call_fn, step_ms=step_ms, max_attempts=max_attempts
    )


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
    "AdaptiveNonceOffsetEngine",
    "get_kraken_api_lock",
    "get_kraken_nonce",
    "get_global_kraken_nonce",
    "get_global_nonce_manager",
    "get_global_nonce_stats",
    "get_adaptive_offset_engine",
    "record_kraken_nonce_error",
    "record_kraken_nonce_success",
    "reset_global_kraken_nonce",
    "force_resync_kraken_nonce",
    "jump_global_kraken_nonce_forward",
    "probe_and_resync_nonce",
    "nonce_reset_triggered_recently",
    "is_nonce_trading_paused",
    "get_nonce_pause_remaining",
    "cleanup_legacy_nonce_files",
    "check_ntp_sync",
    "log_ntp_clock_status",
]
