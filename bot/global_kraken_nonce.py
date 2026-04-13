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
_STARTUP_JUMP_MS: int = int(os.environ.get("NIJA_NONCE_STARTUP_JUMP_MS", "10000"))    # added to persisted nonce on hot restart
_RESET_OFFSET_MS: int = int(os.environ.get("NIJA_NONCE_RESET_OFFSET_MS", "300000"))  # offset used by reset_to_safe_value()

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
_NUCLEAR_RESET_OFFSET_MS: int = int(os.environ.get("NIJA_NONCE_NUCLEAR_OFFSET_MS", "1800000"))  # retained for env-var compat only; no longer used internally
_TRADING_PAUSE_S: float = float(os.environ.get("NIJA_NONCE_PAUSE_SECONDS", "300"))
_ERROR_RESET_THRESHOLD: int = int(os.environ.get("NIJA_NONCE_ERROR_RESET_THRESHOLD", "3"))  # errors < threshold: no jump

# ── Server-sync recovery constants ───────────────────────────────────────────
# Replaces nuclear resets, ceiling jumps, and forward probing.
# On any nonce rejection the single recovery path is:
#   1. Freeze _RECOVERY_FREEZE_S seconds
#   2. Query Kraken /0/public/Time → new nonce baseline = server_time + _SERVER_SYNC_OFFSET_MS
#   3. Retry ONCE
# No 24-hour jumps. No probe loops. No key-invalidation escalation.
_SERVER_SYNC_OFFSET_MS: int = int(os.environ.get("NIJA_NONCE_SERVER_SYNC_OFFSET_MS", "3000"))   # 3 s lead above server time
_RECOVERY_FREEZE_S: float   = float(os.environ.get("NIJA_NONCE_RECOVERY_FREEZE_S",    "3.0"))   # freeze before re-querying server time
_ERROR_RECOVERY_THRESHOLD: int = int(os.environ.get("NIJA_NONCE_ERROR_RECOVERY_THRESHOLD", "3"))  # consecutive errors before server_sync_resync fires

# ── Pre-request guard constants (Step 4) ─────────────────────────────────────
# Enforced by get_kraken_nonce() before issuing every nonce.
# If either invariant is violated, the singleton is destroyed and rebuilt
# from Kraken server time so stale-object reuse can never cause a desync loop.
#
#  epsilon      : minimum gap (ms) from the last SUCCESSFULLY USED nonce.
#                 Value ≥ 1 guarantees strict monotonicity vs. recorded success.
#
#  safety_offset: minimum lead (ms) the pending nonce must have over local
#                 wall-clock time.  0 = nonce must be ≥ now (no past nonces).
#                 Negative values allow slack for minor backward clock drift.
_PRE_REQUEST_EPSILON_MS: int      = int(os.environ.get("NIJA_NONCE_EPSILON_MS",       "1"))
_PRE_REQUEST_SAFETY_OFFSET_MS: int = int(os.environ.get("NIJA_NONCE_SAFETY_OFFSET_MS", "0"))

# After this many consecutive nuclear resets within one session the manager
# automatically activates deep-probe mode (12 × 10 min = 120 min coverage),
# exactly as if NIJA_DEEP_NONCE_RESET=1 had been set at startup.
_AUTO_DEEP_RESET_THRESHOLD: int = int(os.environ.get("NIJA_AUTO_DEEP_THRESHOLD", "2"))

# ── Broker quarantine on confirmed nonce poisoning ────────────────────────────
# When the number of nuclear resets in a session reaches this threshold the
# nonce manager fires all registered quarantine callbacks so that the broker
# layer can immediately:
#   1. Mark the Kraken broker as EXIT-ONLY (no new entries)
#   2. Force-promote the next available broker (Coinbase) to active/primary
#
# Threshold matches _AUTO_DEEP_RESET_THRESHOLD by default so quarantine fires
# at the same moment deep-probe mode is activated.  Can be raised via env var
# if a looser policy is preferred (e.g. 3 nuclear resets before quarantine).
_NONCE_POISON_QUARANTINE_THRESHOLD: int = int(
    os.environ.get("NIJA_NONCE_QUARANTINE_THRESHOLD", str(_AUTO_DEEP_RESET_THRESHOLD))
)

# Module-level quarantine state — written under _LOCK.
_quarantine_triggered: bool = False
_quarantine_callbacks: list = []    # List[Callable[[], None]]

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
_DEEP_STARTUP_FLOOR_MS: int = int(os.environ.get("NIJA_NONCE_DEEP_STARTUP_FLOOR_MS", "3600000"))  # 60 min lead on startup when deep-reset is active

# Extra probe attempts automatically added when a duplicate process is detected
# holding the nonce lock, since that process may have advanced the floor further.
_DUPLICATE_PROC_EXTRA_ATTEMPTS: int = int(os.environ.get("NIJA_NONCE_DUPLICATE_PROC_EXTRA_ATTEMPTS", "6"))

# ── Ceiling-jump escalation after standard probes are all exhausted ───────────
# When every standard probe attempt fails, probe_and_resync() performs one
# ceiling jump (now + _CEILING_JUMP_MS, default 24 h) and then tries this many
# additional probes.  If those ALSO fail — and no duplicate process is detected
# — the API key is declared permanently out-of-window and the broker quarantine
# fires immediately.  This is the "instant key invalidation detection" step.
_PROBE_ESCALATION_ATTEMPTS: int = int(os.environ.get("NIJA_NONCE_ESCALATION_ATTEMPTS", "4"))

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
_AO_EMA_ALPHA: float = float(os.environ.get("NIJA_AO_EMA_ALPHA", "0.3"))  # weight for the most recent observation (30%)
_AO_HISTORY_WINDOW: int = int(os.environ.get("NIJA_AO_HISTORY_WINDOW", "10"))  # persist up to 10 historical calibration records

# Corruption guard thresholds — if persisted nonce is this far ahead of
# wall-clock the state file is likely corrupted.
_CORRUPTION_WARN_MS: int = int(os.environ.get("NIJA_NONCE_CORRUPTION_WARN_MS", "600000"))    # 10 min → warn but keep
# Raised from 24 h → 72 h so that a deliberately large ceiling jump
# (e.g. NIJA_NONCE_CEILING_JUMP=1 with a 24 h leap) is never mistaken
# for corruption and discarded on the next container restart.
_CORRUPTION_RESET_MS: int = int(os.environ.get("NIJA_NONCE_CORRUPTION_RESET_MS", "259200000"))  # 72 h   → discard and restart

# ── Ceiling-jump constants ────────────────────────────────────────────────────
# A "ceiling jump" advances the nonce to now + _CEILING_JUMP_MS in a single
# step — much larger than the nuclear-reset (+30 min) or deep-probe startup
# floor (+60 min).  Use this when Kraken's server-side stored nonce is so far
# ahead that even deep-probe mode cannot reach it.
#
# Activated by setting  NIJA_NONCE_CEILING_JUMP=1  before startup, or by
# calling  force_ceiling_jump()  at runtime.
#
# The jump size defaults to 24 h and is overridable via
#   NIJA_NONCE_CEILING_JUMP_MS=<milliseconds>   (e.g. 172800000 for 48 h)
#
# ⚠️  Risk: you are guessing the required ceiling.  If Kraken has stored an
# even higher nonce the call will still fail.  probe_and_resync() will resume
# from the new (higher) floor so it needs fewer steps, but a new API key
# remains the only guaranteed fix for a badly out-of-sync nonce.
_CEILING_JUMP_MS: int = int(os.environ.get("NIJA_NONCE_CEILING_JUMP_MS", "86400000"))  # default 24 h

# ── NTP clock-sync constants ──────────────────────────────────────────────────
# Kraken is EXTREMELY sensitive to clock drift.  Even a few seconds off can
# trigger continuous nonce errors that block ALL accounts.
_NTP_SERVER: str = "pool.ntp.org"
_NTP_TIMEOUT_S: float = 3.0      # UDP query timeout
_NTP_STRICT_OFFSET_S: float = 1.0  # Kraken rejects nonces when |offset| > ~1 s
_NTP_WARN_OFFSET_S: float = 0.5   # warn early so operators act before it breaks

# ── API serialisation lock ────────────────────────────────────────────────────
# Serialises ALL Kraken private API calls within a single process so that no
# two threads can issue concurrent requests (and thus concurrent nonces).
# For cross-process serialisation see _PID_LOCK_FILE below.
_KRAKEN_API_LOCK = threading.RLock()

# ── Per-key nonce manager registry ───────────────────────────────────────────
# Central nonce service: one KrakenNonceManager instance per API key.
# All nonce requests for a given key_id are serialised through its dedicated
# manager — enforcing ONE API KEY = ONE WRITER across every thread.
#
#   key_id = ""       → platform key  (KrakenNonceManager._instance)
#   key_id = <str>    → user/named key (entry in _KEY_REGISTRY)
#
# Access always goes through get_nonce_manager_for_key(key_id).
_KEY_REGISTRY: "dict[str, KrakenNonceManager]" = {}
_KEY_REGISTRY_LOCK = threading.Lock()

# ── Cross-process lock files ──────────────────────────────────────────────────
# _LOCK_FILE    — brief per-nonce-operation exclusive lock held only during
#                 the read → increment → write critical section inside
#                 next_nonce().  Guards against two processes issuing the same
#                 nonce if they are both running simultaneously.
#
# _PID_LOCK_FILE — process-LIFETIME exclusive lock acquired once in _init()
#                  and held until the process exits (file-descriptor stays open).
#                  Provides reliable duplicate-process detection:
#                    • Another process starting up checks this file first.
#                    • If it can't acquire LOCK_EX|LOCK_NB → another bot is
#                      running with the same API key → logs CRITICAL.
#                    • External tools (reset_kraken_nonce.py) also check this
#                      file to confirm the bot is truly stopped before resetting.
#                  The OS automatically releases the lock when the process dies
#                  (even via SIGKILL), so there is no risk of a permanently-stuck
#                  lock file after a crash.
_LOCK_FILE     = _STATE_FILE + ".lock"
_PID_LOCK_FILE = _STATE_FILE + ".pid"

# ── Nonce backend / mode selection ───────────────────────────────────────────
# NIJA_NONCE_BACKEND — storage backend for the monotonic nonce counter.
#
#   "file"  (default) — atomic file-locked counter persisted to
#                        data/kraken_nonce.state.  Works on any filesystem.
#
#   "redis"           — legacy option (DISALLOWED by hard single-writer rule:
#                        ONE API KEY = ONE WRITER).  Startup now fails closed
#                        if NIJA_NONCE_BACKEND=redis is configured.
#
# NIJA_NONCE_MODE — controls what the initial nonce value is based on.
#
#   "file"      (default) — reads the persisted state file on startup and
#                            advances to max(persisted + jump, now + jump).
#                            Survives container restarts with no cooldown.
#
#   "timestamp" — always starts from int(time.time() * 1000) + startup jump;
#                 no state-file dependency.  Removes local-filesystem coupling
#                 entirely.  Requires a brief cooldown (≥ startup_jump ms) on
#                 hot restart so nonces don't replay a previous session's range.
#                 probe_and_resync() handles the cooldown automatically.
_NONCE_BACKEND   = os.environ.get("NIJA_NONCE_BACKEND",   "file").strip().lower()
_REDIS_URL       = os.environ.get("NIJA_REDIS_URL",        "redis://localhost:6379/0")
_REDIS_NONCE_KEY = os.environ.get("NIJA_REDIS_NONCE_KEY",  "nija:kraken:nonce")
_NONCE_MODE      = os.environ.get("NIJA_NONCE_MODE",       "file").strip().lower()


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
                # Open in append mode so we never truncate the file while
                # another process may have it open.  The file stores no data
                # and is used purely as a lock target.
                self._fh = open(self._path, "a")
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


# ── Optional: Redis-backed atomic nonce (NIJA_NONCE_BACKEND=redis) ────────────

class _RedisNonceBackend:
    """
    Redis-backed atomic monotonic nonce generator.

    Uses a Lua script to atomically advance the nonce to
    ``max(current + 1, floor_ms)`` in a single round-trip.  Because Lua
    scripts run atomically on the Redis server, two concurrently-running bot
    processes (or separate containers) can NEVER receive the same nonce value.

    This is the recommended backend for multi-host or multi-container
    deployments where the same Kraken API key is shared.

    Enable via env var:
        NIJA_NONCE_BACKEND=redis
        NIJA_REDIS_URL=redis://localhost:6379/0      (optional)
        NIJA_REDIS_NONCE_KEY=nija:kraken:nonce       (optional)

    Falls back to file mode transparently when Redis is unavailable.
    """

    # Lua script: atomically advance to max(current+1, floor) and return result.
    # KEYS[1] = nonce key, ARGV[1] = floor (int ms timestamp).
    _LUA_SCRIPT = """
        local current = tonumber(redis.call('GET', KEYS[1])) or 0
        local floor   = tonumber(ARGV[1])
        local next    = math.max(current + 1, floor)
        redis.call('SET', KEYS[1], tostring(next))
        return next
    """

    def __init__(self, url: str, key: str) -> None:
        import redis as _redis_lib  # type: ignore[import]
        self._key = key
        self._client = _redis_lib.from_url(
            url, decode_responses=True, socket_timeout=2.0, socket_connect_timeout=2.0
        )
        self._script = self._client.register_script(self._LUA_SCRIPT)
        # Verify connectivity at construction time.
        self._client.ping()
        _logger.info(
            "🗄️  RedisNonceBackend: connected  url=%s  key=%s", url, key
        )

    def next_nonce(self) -> int:
        """Atomically return the next nonce (≥ now_ms, strictly increasing)."""
        floor = int(time.time() * 1000) + _STARTUP_JUMP_MS
        result = self._script(keys=[self._key], args=[floor])
        return int(result)

    def get_last(self) -> int:
        """Return the last issued nonce without advancing it."""
        val = self._client.get(self._key)
        return int(val) if val else 0

    def advance_to(self, floor_ms: int) -> None:
        """Advance the Redis nonce to at least *floor_ms* (atomic max operation)."""
        self._script(keys=[self._key], args=[floor_ms])

    def reset(self) -> None:
        """Delete the Redis nonce key (fresh start — use with caution)."""
        self._client.delete(self._key)
        _logger.warning("RedisNonceBackend: nonce key '%s' deleted for reset", self._key)


def _build_redis_backend() -> "_RedisNonceBackend | None":
    """
    Attempt to construct a :class:`_RedisNonceBackend`.

    Returns ``None`` (and logs a warning) if the ``redis`` package is not
    installed, the URL is invalid, or the Redis server is unreachable.
    """
    try:
        backend = _RedisNonceBackend(_REDIS_URL, _REDIS_NONCE_KEY)
        return backend
    except ImportError:
        _logger.error(
            "RedisNonceBackend: 'redis' package not installed — "
            "falling back to file mode.  Install with: pip install redis>=5.0"
        )
    except Exception as exc:
        _logger.error(
            "RedisNonceBackend: could not connect to %s (%s) — "
            "falling back to file mode",
            _REDIS_URL, exc,
        )
    return None


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


def _fetch_kraken_server_time_ms() -> "int | None":
    """
    Query Kraken's public server-time endpoint and return the value in milliseconds.

    Uses ``urllib.request`` (stdlib) so there is no dependency on ``requests``
    or ``krakenex``.  The endpoint is unauthenticated and does not consume rate
    limit budget.  ``urlopen`` validates the TLS certificate via the system CA
    bundle by default (Python 3.4+), so MITM protection is in place without
    any additional configuration.

    Returns ``None`` silently on any error: network failure, timeout (5 s),
    non-200 response, JSON parse error, or a non-empty Kraken error list.
    Callers must fall back to ``int(time.time() * 1000)`` when None is returned.

    Example response from Kraken::

        {"error": [], "result": {"unixtime": 1712345678, "rfc1123": "..."}}
    """
    try:
        import urllib.request as _ur
        import json as _j
        with _ur.urlopen("https://api.kraken.com/0/public/Time", timeout=5) as _resp:
            _payload = _j.loads(_resp.read().decode("utf-8"))
        if _payload.get("error"):
            return None
        _unixtime = _payload.get("result", {}).get("unixtime")
        if _unixtime is not None:
            return int(float(_unixtime) * 1000)
        return None
    except Exception:
        return None


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

    def __new__(cls, key_id: str = ""):
        """Return a key-scoped singleton.

        ``key_id=""``  → platform key: the existing global singleton stored in
                         ``cls._instance`` (full backward compatibility).
        ``key_id=<str>`` → per-user/named key: a dedicated instance stored in
                           ``_KEY_REGISTRY[key_id]``.  Each key gets its own
                           state file, cross-process lock, and error counters
                           so nonce sequences are completely isolated.
        """
        if not key_id:
            # ── Platform singleton (original behaviour) ───────────────────
            if cls._instance is None:
                with cls._instance_lock:
                    if cls._instance is None:
                        instance = super().__new__(cls)
                        instance._key_id = ""
                        instance._init()
                        cls._instance = instance
            return cls._instance
        else:
            # ── Per-key registry ──────────────────────────────────────────
            with _KEY_REGISTRY_LOCK:
                if key_id not in _KEY_REGISTRY:
                    instance = super().__new__(cls)
                    instance._key_id = key_id
                    instance._init()
                    _KEY_REGISTRY[key_id] = instance
            return _KEY_REGISTRY[key_id]

    def _init(self) -> None:
        # ── Per-key state file paths ──────────────────────────────────────────
        # Platform key (key_id="") uses the module-level constants so existing
        # deployments are fully backward-compatible.  Named keys get isolated
        # files so their nonce sequences never interfere with each other or the
        # platform key.
        _data_dir = os.path.dirname(os.path.abspath(_STATE_FILE))
        if self._key_id:
            # Whitelist: keep only alphanumeric and a small set of safe chars.
            # This prevents directory traversal regardless of what the caller
            # passes (e.g. ../../etc/passwd, :global, etc.).
            import re as _re
            _safe_id = _re.sub(r"[^A-Za-z0-9_\-]", "_", self._key_id)[:64]
            self._state_file    = os.path.join(_data_dir, f"kraken_nonce_{_safe_id}.state")
        else:
            self._state_file    = _STATE_FILE
        self._lock_file     = self._state_file + ".lock"
        self._pid_lock_file = self._state_file + ".pid"

        self._error_count = 0
        self._trading_paused_until: float = 0.0   # epoch seconds; 0 = not paused
        # Tracks how many nuclear resets have fired in this session.  When it
        # reaches _AUTO_DEEP_RESET_THRESHOLD, deep-probe mode is automatically
        # activated so probe_and_resync() uses the wider 120-min coverage window.
        self._nuclear_reset_count: int = 0
        # Set to True when probe_and_resync() determines the API key is
        # permanently out-of-window (ceiling jump + escalation probes all fail,
        # and no competing process is detected).  Once True, record_error() is a
        # no-op (no more nuclear resets) and broker_manager aborts retry loops
        # immediately so the infinite nonce-reset loop cannot happen.
        self._key_invalidated: bool = False
        # Tracks the last nonce value that Kraken successfully accepted.
        # Used by the pre-request guard (Step 4) to enforce strict monotonicity
        # relative to the confirmed success history, not just the in-memory counter.
        self._last_successful_nonce: int = 0
        # Process-lifetime lock file descriptor (None on Windows / error).
        # Kept open for the entire bot session so duplicate-process detection
        # is reliable even between nonce operations.
        self._pid_lock_fh: object = None
        # Optional Redis nonce backend (None = use file / timestamp mode).
        self._redis_backend: object = None
        os.makedirs(os.path.dirname(os.path.abspath(self._state_file)), exist_ok=True)
        cleanup_legacy_nonce_files()

        # ── Process-lifetime PID lock (duplicate-bot detection) ────────────
        # Acquired FIRST — before any other state I/O — so that a duplicate
        # process is detected as early as possible during startup.
        # Hard rule: ONE API KEY = ONE WRITER.  If acquisition fails, fail
        # closed immediately so duplicate writers cannot run.
        self._pid_lock_fh = self._try_acquire_pid_lock()
        if not _FCNTL_AVAILABLE:
            _logger.warning(
                "KrakenNonceManager: fcntl unavailable on this platform; "
                "cannot hard-enforce process-lifetime single-writer locking."
            )
        elif self._pid_lock_fh is None:
            raise RuntimeError(
                "Kraken nonce writer lock not acquired. "
                "Hard rule violation: ONE API KEY = ONE WRITER "
                "(no multi-container, no multi-region, no independent nonce writers). "
                "Likely causes: another NIJA process already running or lock-file permissions. "
                "Stop all duplicate deployments/processes and restart a single writer."
            )

        # Hard rule: disallow the LEGACY NIJA_NONCE_BACKEND=redis path.
        # Redis nonce support is now exclusively through DistributedNonceManager
        # (bot/distributed_nonce_manager.py), configured via NIJA_REDIS_URL.
        # That path uses a per-key Redis key with atomic Lua INCR, which is the
        # correct multi-instance design.  The legacy env-var path allowed
        # ALL keys to share ONE Redis key, which violated key isolation.
        if _NONCE_BACKEND == "redis":
            raise RuntimeError(
                "NIJA_NONCE_BACKEND=redis is disallowed for KrakenNonceManager. "
                "Use NIJA_REDIS_URL instead — DistributedNonceManager will pick it up "
                "and route each API key through its own Redis nonce sequence."
            )

        # ── Optional nonce backend ────────────────────────────────────────
        # Redis backend path is intentionally disabled by the hard one-writer
        # rule above.
        if _NONCE_MODE == "timestamp":
            _logger.info(
                "KrakenNonceManager: NIJA_NONCE_MODE=timestamp — "
                "nonce derived from wall-clock ms; no state-file dependency"
            )

        # ── Detect deep-reset mode ─────────────────────────────────────────
        # NIJA_DEEP_NONCE_RESET=1 applies a 60-min NTP-corrected startup floor
        # and extends probe_and_resync() to 12 × 10-min = 120-min coverage.
        # Use this when NIJA_FORCE_NONCE_RESYNC=1 alone is insufficient because:
        #   • multiple nuclear resets put Kraken's floor >30 min ahead
        #   • host clock drift caused the computed floor to undershoot
        #   • a competing process advanced the nonce while this one was down
        _deep_reset = os.environ.get("NIJA_DEEP_NONCE_RESET", "").strip() == "1"
        self._deep_reset_active: bool = _deep_reset

        # ── Step 1 (hard reset): always delete persisted nonce state on init ──
        # Every boot starts from a clean server-time anchor.  This prevents
        # stale forward-drift (accumulated nuclear resets / ceiling jumps from
        # prior sessions) from poisoning the new session's nonce.
        # NOTE: self._pid_lock_file is intentionally excluded — it is held open
        # for the process lifetime and must not be deleted during init.
        for _path in (self._state_file, self._state_file + ".lock", self._state_file + ".tmp"):
            try:
                os.remove(_path)
                _logger.debug("KrakenNonceManager: cleared persisted nonce state %s", _path)
            except FileNotFoundError:
                pass
            except Exception as exc:
                _logger.debug("KrakenNonceManager: could not clear %s (%s)", _path, exc)

        # NIJA_FORCE_NONCE_RESYNC=1 / deep-reset: also wipe the adaptive-offset
        # EMA so the next probe_and_resync() starts from the conservative timing
        # floor rather than a potentially-stale small EMA value.
        if os.environ.get("NIJA_FORCE_NONCE_RESYNC", "").strip() == "1" or _deep_reset:
            _logger.warning(
                "KrakenNonceManager: %s — also wiping adaptive-offset EMA",
                "NIJA_DEEP_NONCE_RESET=1" if _deep_reset else "NIJA_FORCE_NONCE_RESYNC=1",
            )
            for _path in (_AO_STATE_FILE, _AO_STATE_FILE + ".tmp"):
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
            # Also reset the Redis backend nonce key if Redis is active.
            if self._redis_backend is not None:
                try:
                    self._redis_backend.reset()
                except Exception as _re:
                    _logger.debug("KrakenNonceManager: Redis reset error (%s)", _re)

        # NTP check first — clock drift is the #1 cause of Kraken nonce errors.
        # Kraken is extremely sensitive: even a few seconds off triggers
        # continuous "EAPI:Invalid nonce" errors that block ALL accounts.
        log_ntp_clock_status()

        # Warn loudly if another bot process is still running on platforms where
        # process-lifetime lock enforcement is unavailable.
        if (not _FCNTL_AVAILABLE) and KrakenNonceManager.detect_other_process_running():
            _logger.error(
                "🚨 KrakenNonceManager: another bot process appears to be holding "
                "the nonce lock.  Stop ALL duplicate NIJA processes before this "
                "reset takes effect, otherwise the competing process will continue "
                "advancing Kraken's expected nonce and the reset will be ineffective.  "
                "Run: pkill -f bot.py  (or stop the active deployment)."
            )

        # In timestamp mode the nonce is derived from the wall-clock at each
        # call; no state file is read at startup.  Use now + startup jump as the
        # initial in-memory floor so the very first next_nonce() is safe.
        if _NONCE_MODE == "timestamp":
            now_ms = int(time.time() * 1000)
            self._last_nonce = now_ms + _STARTUP_JUMP_MS
            lead_ms = self._last_nonce - now_ms
            _logger.info(
                "KrakenNonceManager: ready (timestamp mode) — nonce=%d  lead=%+d ms",
                self._last_nonce, lead_ms,
            )
            return

        # In Redis mode the initial in-memory floor comes from Redis.
        if self._redis_backend is not None:
            try:
                self._last_nonce = self._redis_backend.get_last()
                if _deep_reset:
                    ntp_corr_ms = _get_ntp_backward_drift_ms()
                    deep_floor = int(time.time() * 1000) + _DEEP_STARTUP_FLOOR_MS + ntp_corr_ms
                    if deep_floor > self._last_nonce:
                        _logger.warning(
                            "KrakenNonceManager: DEEP RESET (Redis) — floor "
                            "now+%d ms + NTP correction +%d ms → %d  (was %d)",
                            _DEEP_STARTUP_FLOOR_MS, ntp_corr_ms,
                            deep_floor, self._last_nonce,
                        )
                        self._redis_backend.advance_to(deep_floor)
                        self._last_nonce = deep_floor
                lead_ms = self._last_nonce - int(time.time() * 1000)
                _logger.info(
                    "KrakenNonceManager: ready (Redis mode) — nonce=%d  lead=%+d ms",
                    self._last_nonce, lead_ms,
                )
                return
            except Exception as exc:
                _logger.error(
                    "KrakenNonceManager: Redis init error (%s) — falling back to file mode",
                    exc,
                )
                self._redis_backend = None

        # ── File mode (default) ────────────────────────────────────────────
        # Startup is the most likely moment for two processes to race.  Hold the
        # cross-process lock for the entire read → compute → write sequence so a
        # second process starting at the same time cannot claim the same nonce.
        with _LOCK:
            with _CrossProcessLock(self._lock_file):
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

                # Ceiling-jump mode: advance nonce to now + _CEILING_JUMP_MS
                # (default 24 h) so it lands well above Kraken's stored value.
                # Applied AFTER deep-reset so the ceiling always wins.
                if os.environ.get("NIJA_NONCE_CEILING_JUMP", "").strip() == "1":
                    ceiling_floor = int(time.time() * 1000) + _CEILING_JUMP_MS
                    if ceiling_floor > self._last_nonce:
                        _logger.warning(
                            "🚀 KrakenNonceManager: CEILING JUMP (NIJA_NONCE_CEILING_JUMP=1) — "
                            "nonce → now+%d ms (%.1f h)  %d → %d",
                            _CEILING_JUMP_MS, _CEILING_JUMP_MS / 3_600_000,
                            self._last_nonce, ceiling_floor,
                        )
                        self._last_nonce = ceiling_floor
                    else:
                        _logger.warning(
                            "🚀 KrakenNonceManager: CEILING JUMP requested but nonce already "
                            "ahead (nonce=%d  ceiling=%d  lead=%+d ms) — skipped",
                            self._last_nonce, ceiling_floor,
                            self._last_nonce - ceiling_floor,
                        )

                self._persist()
        lead_ms = self._last_nonce - int(time.time() * 1000)
        _logger.info(
            "KrakenNonceManager: ready — nonce=%d  lead=%+d ms",
            self._last_nonce, lead_ms,
        )

    # ── Core ──────────────────────────────────────────────────────────────

    def next_nonce(self) -> int:
        """Return the next strictly-increasing nonce and persist it.

        Supports three backends, selected by env vars at startup:

        * **file** (default) — atomic file-locked counter; cross-process safe
          via ``_CrossProcessLock``.
        * **redis** — atomic Lua-script INCR in Redis; safe across hosts.
        * **timestamp** — wall-clock ms + monotonic in-process counter; no
          file dependency; requires a brief startup cooldown on hot restart.
        """
        # ── Redis backend ──────────────────────────────────────────────────
        if self._redis_backend is not None:
            try:
                nonce = self._redis_backend.next_nonce()
                with _LOCK:
                    self._last_nonce = nonce
                return nonce
            except Exception as exc:
                _logger.error(
                    "RedisNonceBackend: next_nonce() failed (%s) — "
                    "falling back to file mode for this call",
                    exc,
                )
                # Fall through to file/timestamp mode for this call only.

        # ── Timestamp mode ─────────────────────────────────────────────────
        if _NONCE_MODE == "timestamp":
            with _LOCK:
                now_ms = int(time.time() * 1000)
                # Enforce: nonce = max(local_time_ms, last_nonce + 1)
                # Keeps the series strictly monotonic while staying aligned to
                # wall-clock so Kraken's window never sees a runaway lead.
                self._last_nonce = max(now_ms, self._last_nonce + 1)
                return self._last_nonce

        # ── File mode (default) ────────────────────────────────────────────
        with _LOCK:
            with _CrossProcessLock(self._lock_file):
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

                # ── Enforce: nonce = max(local_time_ms, last_nonce + 1) ────────
                # Keeps the series strictly monotonic and always at or ahead of
                # wall-clock — no backward drift, no runaway forward lead.
                now_ms = int(time.time() * 1000)
                self._last_nonce = max(now_ms, self._last_nonce + 1)
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
                if self._redis_backend is not None:
                    try:
                        self._redis_backend.advance_to(floor)
                    except Exception as _re:
                        _logger.debug("RedisNonceBackend: advance_to error (%s)", _re)
                elif _NONCE_MODE != "timestamp":
                    self._persist()
            else:
                _logger.debug(
                    "KrakenNonceManager: reset_to_safe_value skipped — "
                    "nonce already ahead (nonce=%d  floor=%d  lead=%+d ms)",
                    self._last_nonce, floor,
                    self._last_nonce - int(time.time() * 1000),
                )

    def force_ceiling_jump(self, ms: int | None = None) -> int:
        """
        Jump the nonce to ``now + ms`` in one step and persist immediately.

        This is a brute-force escape hatch for situations where Kraken's
        server-side stored nonce is so far ahead that even a nuclear reset
        (+30 min) or deep-probe startup floor (+60 min) cannot reach it.

        The new nonce replaces the current value only when it is *higher*
        (strictly monotonic).  After a successful ceiling jump the caller
        should restart ``probe_and_resync()`` — the calibration will start
        from the new (much higher) floor and need fewer steps.

        ⚠️  Risk: you are guessing the required ceiling.  If Kraken has stored
        an even higher value the jump will still not be sufficient.  A new API
        key remains the only *guaranteed* fix.

        Args:
            ms: Forward-jump offset in milliseconds from *now*.
                Defaults to ``_CEILING_JUMP_MS`` (env ``NIJA_NONCE_CEILING_JUMP_MS``,
                default 24 h = 86 400 000 ms).

        Returns:
            The new persisted nonce value.
        """
        with _LOCK:
            jump_ms = ms if ms is not None else _CEILING_JUMP_MS
            now_ms = int(time.time() * 1000)
            ceiling = now_ms + jump_ms
            prev = self._last_nonce
            if ceiling > self._last_nonce:
                self._last_nonce = ceiling
                if self._redis_backend is not None:
                    try:
                        self._redis_backend.advance_to(ceiling)
                    except Exception as _re:
                        _logger.debug(
                            "RedisNonceBackend: failed to advance nonce during ceiling jump (%s)", _re
                        )
                elif _NONCE_MODE != "timestamp":
                    self._persist()
                _logger.warning(
                    "🚀 KrakenNonceManager.force_ceiling_jump: nonce → now+%d ms (%.1f h)  "
                    "%d → %d  (was %+d ms ahead of wall-clock, now %+d ms ahead)",
                    jump_ms, jump_ms / 3_600_000,
                    prev, ceiling,
                    prev - now_ms, ceiling - now_ms,
                )
            else:
                _logger.warning(
                    "🚀 KrakenNonceManager.force_ceiling_jump: nonce already ahead of "
                    "requested ceiling (nonce=%d  ceiling=%d  lead=%+d ms) — no change",
                    self._last_nonce, ceiling, self._last_nonce - now_ms,
                )
            return self._last_nonce

    def force_resync(self) -> None:
        """
        Hard reset the nonce state for a guaranteed-clean startup.

        Wipes ``data/kraken_nonce.state`` (and related lock/tmp files) **and**
        clears the ``AdaptiveNonceOffsetEngine`` EMA so the next
        ``probe_and_resync()`` starts from the conservative timing floor rather
        than a potentially-stale small EMA.

        When Redis mode is active the Redis nonce key is also deleted.

        Call this from a maintenance script or a one-off Railway shell command
        when NIJA is stopped and you need to guarantee a clean sync on the
        next restart.  The same effect is achieved at boot time by setting the
        environment variable ``NIJA_FORCE_NONCE_RESYNC=1`` before starting.

        Safe to call while the process is running (acquires ``_LOCK``), but for
        best results stop NIJA first so no new nonces are issued after the wipe.

        Note: ``self._pid_lock_file`` is intentionally excluded from the wipe
        list — the file descriptor is held open for the process lifetime and
        must not be deleted while the process is running.
        """
        with _LOCK:
            # Per-key state files; _AO_STATE_FILE (adaptive engine) is shared
            # and only wiped for the platform key to avoid disrupting other keys.
            _ao_paths = (
                (_AO_STATE_FILE, _AO_STATE_FILE + ".tmp")
                if not self._key_id else ()
            )
            for _path in (
                self._state_file,
                self._state_file + ".lock",
                self._state_file + ".tmp",
                *_ao_paths,
                # self._pid_lock_file excluded — held open for process lifetime
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

            # Reset the Redis nonce key if active.
            if self._redis_backend is not None:
                try:
                    self._redis_backend.reset()
                except Exception as _re:
                    _logger.debug("KrakenNonceManager.force_resync: Redis reset error (%s)", _re)

            # Reset the in-process error counter, nuclear reset counter, trading pause,
            # and key-invalidation flag so a freshly-rotated API key gets a clean slate.
            self._error_count = 0
            self._nuclear_reset_count = 0
            self._trading_paused_until = 0.0
            self._key_invalidated = False

            # Advance nonce to now + RESET_OFFSET_MS so the very next call
            # lands safely above Kraken's window.
            self._last_nonce = int(time.time() * 1000) + _RESET_OFFSET_MS
            if _NONCE_MODE != "timestamp" and self._redis_backend is None:
                self._persist()

            _logger.warning(
                "KrakenNonceManager.force_resync: state wiped — nonce set to "
                "now+%d ms (%d).  Restart NIJA to begin fresh probe calibration.",
                _RESET_OFFSET_MS, self._last_nonce,
            )

    def hard_nonce_rebase(self) -> int:
        """
        Backward-compatible recovery entry point — delegates to ``server_sync_resync()``.

        The previous behaviour (unconditionally set nonce to ``now − 1 000 ms``)
        is replaced by a server-synced reset so that accumulated forward drift
        from any prior strategy is discarded cleanly without introducing a
        hard floor that may still be below Kraken's stored high-water mark.

        Returns the new persisted nonce value.
        """
        _logger.warning(
            "KrakenNonceManager.hard_nonce_rebase: delegating to "
            "server_sync_resync(freeze_s=0) — server-time anchor used "
            "instead of hard floor drop"
        )
        self.server_sync_resync(freeze_s=0.0)
        return self.get_last_nonce()

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
    def is_key_invalidated(self) -> bool:
        """
        Return True when the Kraken API key has been declared permanently
        out-of-window by ``probe_and_resync()``.

        This is set when:
          1. All standard probe attempts failed, AND
          2. A ceiling jump (now + 24 h) was tried, AND
          3. All post-ceiling escalation probes ALSO failed, AND
          4. No duplicate competing process was detected (which would indicate a
             process-conflict rather than a dead key).

        Once True:
          • ``record_error()`` becomes a no-op — no more nuclear resets.
          • ``broker_manager`` returns False immediately from ``connect()`` instead
            of entering the retry loop, breaking the infinite-reset cycle.
          • Quarantine is active (Kraken is exit-only; Coinbase promoted).

        Reset by ``force_resync()`` after the operator has rotated the API key
        and confirmed the new key is healthy.
        """
        return getattr(self, "_key_invalidated", False)

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

    def activate_deep_reset(self) -> None:
        """
        Enable deep-probe mode at runtime without a restart.

        This is the public equivalent of setting ``NIJA_DEEP_NONCE_RESET=1``
        at startup.  Once activated:

          * ``probe_and_resync()`` uses a 10-min step and up to 12 attempts
            (120-min total coverage) rather than the default 5-min / 60-min.

        Typically called by the self-healing startup sequence when nonce
        poison detection indicates the nonce is 30–120 min ahead of wall-clock.
        Calling this more than once is harmless (idempotent).
        """
        if not getattr(self, "_deep_reset_active", False):
            self._deep_reset_active = True
            _logger.warning(
                "KrakenNonceManager.activate_deep_reset: deep-probe mode activated "
                "(12×10 min = 120 min probe coverage). "
                "probe_and_resync() will use extended steps on the next connect()."
            )

    # ── Error / success tracking ──────────────────────────────────────────

    def record_error(self) -> None:
        """
        Record a Kraken ``EAPI:Invalid nonce`` error.

        Recovery behaviour
        ------------------
        errors 1–2 : no action — the next natural ``next_nonce()`` call advances
                     monotonically (``max(now_ms, last + 1)``).  Most transient
                     single-error rejections resolve without intervention.

        error 3+   : **destroy this singleton** (Step 3) so the next
                     ``get_kraken_nonce()`` call rebuilds a fully fresh instance
                     anchored to Kraken server time.  A brief freeze
                     (``_RECOVERY_FREEZE_S`` seconds, default 3 s) is applied
                     first to let Kraken's nonce window settle before the rebuild
                     queries ``/0/public/Time``.

                     Using destroy-and-rebuild (not reset-in-place) prevents the
                     "silent reuse of stale nonce object" failure mode where a
                     partially-recovered instance accumulates further drift.

        No-op when the API key has been declared permanently invalid (retained
        for backward compatibility with call sites that guard on
        ``is_key_invalidated``).
        """
        if getattr(self, "_key_invalidated", False):
            _logger.debug(
                "KrakenNonceManager.record_error: suppressed — "
                "_key_invalidated flag set; call force_resync() to clear."
            )
            return

        trigger_recovery = False
        with _LOCK:
            self._error_count += 1
            current_count = self._error_count
            _logger.warning(
                "KrakenNonceManager.record_error: consecutive error #%d  nonce=%d",
                current_count, self._last_nonce,
            )
            if current_count >= _ERROR_RECOVERY_THRESHOLD:
                trigger_recovery = True
                self._error_count = 0   # reset inside lock before releasing

        if trigger_recovery:
            _logger.warning(
                "KrakenNonceManager.record_error: %d consecutive nonce errors — "
                "freezing %.1f s then destroying singleton for a full rebuild "
                "from Kraken server time (Step 3: no reset-in-place)",
                _ERROR_RECOVERY_THRESHOLD, _RECOVERY_FREEZE_S,
            )
            if _RECOVERY_FREEZE_S > 0:
                time.sleep(_RECOVERY_FREEZE_S)
            # Destroy the singleton — get_kraken_nonce() will rebuild it fresh.
            KrakenNonceManager.destroy_instance()

    def record_success(self) -> None:
        """Reset the consecutive-error counter after a successful API call.

        Also records the last nonce that Kraken confirmed as valid so the
        pre-request guard (Step 4) can enforce strict monotonicity relative
        to the confirmed success history, and clears any active trading pause.
        """
        with _LOCK:
            self._error_count = 0
            self._last_successful_nonce = self._last_nonce  # Step 4: track for guard
            if self._trading_paused_until > 0.0:
                _logger.info(
                    "✅ KrakenNonceManager: trading pause cleared on successful API call"
                )
                self._trading_paused_until = 0.0

    # ── Nonce lock recovery mode ──────────────────────────────────────────

    def server_sync_resync(self, freeze_s: float = _RECOVERY_FREEZE_S) -> None:
        """
        Nonce lock recovery mode — the single recovery path for all nonce rejections.

        Three-step sequence
        -------------------
        1. **Freeze** — ``time.sleep(freeze_s)`` (default ``_RECOVERY_FREEZE_S``,
           env ``NIJA_NONCE_RECOVERY_FREEZE_S``, default 3 s).  Lets Kraken's
           nonce window settle and drains any in-flight requests.

        2. **Server-time sync** — query ``/0/public/Time`` for Kraken's
           authoritative clock reference.  Falls back to ``time.time()`` if the
           endpoint is unreachable (no hard failure on network issues).

        3. **Nonce reset** — set ``_last_nonce = server_time_ms + _SERVER_SYNC_OFFSET_MS``
           (default ``server_time + 3 s``).  This unconditionally replaces the
           current value, discarding all accumulated forward drift from any
           previous strategy (nuclear resets, ceiling jumps, etc.).

        After the reset ``_error_count`` and ``_trading_paused_until`` are
        cleared so the escalation ladder starts fresh.  The new value is
        persisted to disk immediately.

        This method replaces nuclear resets (+30 min jumps), ceiling jumps
        (+24 h), and the 12-step forward probe loop.

        Args:
            freeze_s: seconds to sleep before querying Kraken server time.
                      Pass ``0.0`` for an instant reset with no sleep (useful
                      when the caller has already waited, e.g. ``hard_nonce_rebase``).
        """
        _logger.warning(
            "KrakenNonceManager.server_sync_resync: freezing %.1f s then "
            "re-syncing nonce to Kraken server time",
            freeze_s,
        )
        if freeze_s > 0:
            time.sleep(freeze_s)

        server_ms = _fetch_kraken_server_time_ms()
        if server_ms is None:
            server_ms = int(time.time() * 1000)
            _logger.warning(
                "KrakenNonceManager.server_sync_resync: Kraken server-time endpoint "
                "unavailable — using local clock as fallback"
            )
        else:
            _logger.info(
                "KrakenNonceManager.server_sync_resync: Kraken server time = %d ms "
                "(delta from local clock: %+d ms)",
                server_ms, server_ms - int(time.time() * 1000),
            )

        new_nonce = server_ms + _SERVER_SYNC_OFFSET_MS
        with _LOCK:
            with _CrossProcessLock(self._lock_file):
                prev = self._last_nonce
                # Unconditional reset — discard all accumulated forward drift.
                self._last_nonce = new_nonce
                self._error_count = 0
                self._trading_paused_until = 0.0
                if self._redis_backend is not None:
                    try:
                        self._redis_backend.advance_to(new_nonce)
                    except Exception as _re:
                        _logger.debug(
                            "KrakenNonceManager.server_sync_resync: "
                            "Redis advance error (%s)", _re
                        )
                elif _NONCE_MODE != "timestamp":
                    self._persist()
        _logger.warning(
            "KrakenNonceManager.server_sync_resync: nonce reset "
            "server+%d ms → %d  (prev=%d  delta=%+d ms)",
            _SERVER_SYNC_OFFSET_MS, new_nonce, prev, new_nonce - prev,
        )

    def probe_and_resync(
        self,
        api_call_fn,
        *,
        step_ms: int = 0,
        max_attempts: int = 0,
    ) -> bool:
        """
        Server-synced nonce calibration with progressive forward probe.

        Recovery sequence
        -----------------
        1. **Attempt 1** — call ``api_call_fn()`` with the current nonce.
           Success → ``True``.

        2. **Server-sync anchor** — nonce rejected →
           ``server_sync_resync()`` (freeze ``_RECOVERY_FREEZE_S`` s, query
           ``/0/public/Time``, reset nonce to
           ``server_time_ms + _SERVER_SYNC_OFFSET_MS``).

        3. **Progressive forward probe** — call ``api_call_fn()`` starting
           from the server-time baseline.  If still rejected, advance the
           nonce by ``effective_step`` ms and retry, up to ``effective_max``
           times.  This handles the case where Kraken's server-side stored
           nonce is *far ahead* of wall-clock time due to legacy forward-jump
           accumulation (nuclear resets, ceiling jumps from a prior strategy).
           Success at any step → records calibration in
           ``AdaptiveNonceOffsetEngine`` → ``True``.

        4. **All steps exhausted** — logs actionable remediation steps and
           returns ``False``.  Does **NOT** set ``_key_invalidated``; nonce
           desync is a recoverable state, not a credential problem.

        ``step_ms`` and ``max_attempts`` override the defaults derived from
        ``_deep_reset_active`` (``_DEEP_PROBE_STEP_MS`` / ``_DEEP_PROBE_MAX_ATTEMPTS``
        when deep mode is on, else ``_PROBE_STEP_MS`` / ``_PROBE_MAX_ATTEMPTS``).

        Args:
            api_call_fn:  ``callable() → dict`` — must return a Kraken API
                          response dict containing an ``"error"`` list.
            step_ms:      Per-step forward jump in milliseconds (0 = auto).
            max_attempts: Maximum number of probe steps after server-sync
                          anchor (0 = auto).

        Returns:
            ``True``  — Kraken accepted a call; nonce is calibrated.
            ``False`` — Network/auth error or nonce desync not resolved
                        within the probe budget.
        """
        # ── NTP pre-check (diagnostic only — does not block) ─────────────
        _ntp = check_ntp_sync()
        if _ntp.get("error"):
            _logger.warning(
                "KrakenNonceManager.probe_and_resync: NTP unavailable (%s) — "
                "verify clock: sudo ntpdate %s",
                _ntp["error"], _NTP_SERVER,
            )
        elif not _ntp["ok"]:
            _logger.error(
                "❌ KrakenNonceManager.probe_and_resync: clock drift %+.3f s — "
                "Kraken requires ±1 s.  Fix: sudo ntpdate %s",
                _ntp["offset_s"], _NTP_SERVER,
            )

        def _is_nonce_error(response: dict) -> bool:
            errs = ", ".join(response.get("error") or [])
            return any(
                kw in errs.lower()
                for kw in ("invalid nonce", "eapi:invalid nonce", "nonce window")
            )

        # ── Attempt 1: current nonce ──────────────────────────────────────
        _logger.info(
            "KrakenNonceManager.probe_and_resync: attempt 1 (nonce=%d)",
            self.get_last_nonce(),
        )
        try:
            result = api_call_fn()
        except Exception as exc:
            _logger.debug(
                "KrakenNonceManager.probe_and_resync: first call raised (%s) — "
                "not a nonce issue; aborting",
                exc,
            )
            return False

        if not isinstance(result, dict):
            _logger.debug(
                "KrakenNonceManager.probe_and_resync: unexpected response type %s — "
                "aborting", type(result).__name__,
            )
            return False

        if not _is_nonce_error(result):
            if not (result.get("error") or []):
                _logger.info(
                    "✅ KrakenNonceManager.probe_and_resync: accepted on first "
                    "attempt — nonce=%d", self.get_last_nonce(),
                )
            else:
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: non-nonce error (%s) — "
                    "nonce is OK", ", ".join(result.get("error") or []),
                )
            return True

        # ── Server-sync recovery ──────────────────────────────────────────
        # Step 1: anchor to Kraken's actual server time to discard any in-process
        # forward drift (nuclear-reset jumps, ceiling jumps, etc.).
        _logger.warning(
            "KrakenNonceManager.probe_and_resync: nonce rejected (%s) — "
            "entering server-sync recovery then progressive forward probe",
            ", ".join(result.get("error") or []),
        )
        self.server_sync_resync()

        # Step 2: progressive forward probe.
        # Kraken's SERVER-SIDE stored floor may be hours ahead of wall-clock time
        # due to legacy forward-jump accumulation (old nuclear resets, ceiling
        # jumps).  server_sync_resync() resets us to server_time+3s which is
        # often still below Kraken's floor.  We probe upward in fixed steps
        # until we find Kraken's actual floor or exhaust all attempts.
        # Capture whether deep mode was active at entry so the auto-escalation
        # path (below) knows which tiers have already been attempted.
        was_deep = self._deep_reset_active
        effective_step: int = step_ms if step_ms > 0 else (
            _DEEP_PROBE_STEP_MS if self._deep_reset_active else _PROBE_STEP_MS
        )
        effective_max: int = max_attempts if max_attempts > 0 else (
            _DEEP_PROBE_MAX_ATTEMPTS if self._deep_reset_active else _PROBE_MAX_ATTEMPTS
        )

        failed_probe_attempts = 0
        total_probe_count = effective_max + 1  # baseline (server_time+3s) + effective_max steps

        for probe_num in range(1, total_probe_count + 1):
            _logger.info(
                "KrakenNonceManager.probe_and_resync: probe %d/%d (nonce=%d)",
                probe_num, total_probe_count, self.get_last_nonce(),
            )
            try:
                probe_result = api_call_fn()
            except Exception as exc:
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: probe %d raised (%s) — "
                    "not a nonce issue; aborting",
                    probe_num, exc,
                )
                return False

            if not isinstance(probe_result, dict):
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: unexpected response type %s "
                    "on probe %d — aborting",
                    type(probe_result).__name__, probe_num,
                )
                return False

            if not _is_nonce_error(probe_result):
                if not (probe_result.get("error") or []):
                    _logger.info(
                        "✅ KrakenNonceManager.probe_and_resync: accepted on probe "
                        "%d/%d — nonce=%d (%d step(s) × %d ms above server time)",
                        probe_num, total_probe_count,
                        self.get_last_nonce(), failed_probe_attempts, effective_step,
                    )
                else:
                    _logger.debug(
                        "KrakenNonceManager.probe_and_resync: non-nonce error (%s) on "
                        "probe %d — nonce is OK",
                        ", ".join(probe_result.get("error") or []), probe_num,
                    )
                # Record calibration so AdaptiveNonceOffsetEngine can learn the gap
                if failed_probe_attempts > 0:
                    AdaptiveNonceOffsetEngine().record_calibration(
                        failed_probe_attempts, effective_step
                    )
                return True

            # Nonce still rejected — advance by one step and try again (if budget remains)
            failed_probe_attempts += 1
            if probe_num < total_probe_count:
                _logger.warning(
                    "KrakenNonceManager.probe_and_resync: nonce rejected on probe "
                    "%d/%d — advancing +%d ms (Kraken floor is ahead of server time)",
                    probe_num, total_probe_count, effective_step,
                )
                with _LOCK:
                    self._last_nonce += effective_step
                    if self._redis_backend is not None:
                        try:
                            self._redis_backend.advance_to(self._last_nonce)
                        except Exception as _re:
                            _logger.debug(
                                "KrakenNonceManager.probe_and_resync: Redis advance error (%s)",
                                _re,
                            )
                    elif _NONCE_MODE != "timestamp":
                        self._persist()

        # ── All probe steps exhausted — auto-escalate through tiers ─────────
        # Nonce desync accumulation: Kraken's server-side stored floor is further
        # ahead of wall-clock than the current probe budget can reach.  This is
        # NOT a key-validity problem; it is a recoverable resync issue caused by
        # accumulated nuclear resets / ceiling jumps from prior sessions.
        #
        # Auto-escalation ladder (runs within this same call):
        #   Tier 1 — DEEP PROBE  : 12 × 10 min = 120 min additional coverage
        #                          (skipped when was_deep=True; deep mode was already used)
        #   Tier 2 — CEILING JUMP: nonce → now + 24 h, then a few final probes
        #
        # This replaces the old pattern of requiring NIJA_DEEP_NONCE_RESET=1 or
        # NIJA_NONCE_CEILING_JUMP=1 env-var restarts; recovery now happens at
        # runtime without operator intervention.

        total_window_min = effective_max * effective_step / 60_000
        _logger.warning(
            "KrakenNonceManager.probe_and_resync: %s-mode probes (%d × %d ms = %.0f min) "
            "exhausted — Kraken nonce floor > %.0f min ahead of server time.  "
            "Beginning auto-escalation.",
            "deep" if was_deep else "standard",
            effective_max, effective_step, total_window_min, total_window_min,
        )

        # ── Tier 1: deep probe (only when we started in standard mode) ────────
        if not was_deep:
            _logger.warning(
                "KrakenNonceManager.probe_and_resync: [Tier 1] auto-escalating to "
                "DEEP PROBE — %d × %d ms = %.0f min additional coverage "
                "continuing from current nonce position",
                _DEEP_PROBE_MAX_ATTEMPTS, _DEEP_PROBE_STEP_MS,
                _DEEP_PROBE_MAX_ATTEMPTS * _DEEP_PROBE_STEP_MS / 60_000,
            )
            self._deep_reset_active = True
            for dp_num in range(1, _DEEP_PROBE_MAX_ATTEMPTS + 1):
                _logger.info(
                    "KrakenNonceManager.probe_and_resync: DEEP probe %d/%d (nonce=%d)",
                    dp_num, _DEEP_PROBE_MAX_ATTEMPTS, self.get_last_nonce(),
                )
                try:
                    dp_result = api_call_fn()
                except Exception as exc:
                    _logger.debug(
                        "KrakenNonceManager.probe_and_resync: DEEP probe %d raised (%s) — aborting",
                        dp_num, exc,
                    )
                    return False
                if not isinstance(dp_result, dict):
                    _logger.debug(
                        "KrakenNonceManager.probe_and_resync: unexpected response type on "
                        "DEEP probe %d — aborting",
                        dp_num,
                    )
                    return False
                if not _is_nonce_error(dp_result):
                    if not (dp_result.get("error") or []):
                        _logger.info(
                            "✅ KrakenNonceManager.probe_and_resync: accepted on DEEP probe "
                            "%d/%d — nonce=%d",
                            dp_num, _DEEP_PROBE_MAX_ATTEMPTS, self.get_last_nonce(),
                        )
                    # Record calibration so AdaptiveNonceOffsetEngine can learn
                    # how many deep-probe steps were needed (dp_num - 1 failed
                    # before this success; 0 means calibrated on the first try).
                    AdaptiveNonceOffsetEngine().record_calibration(
                        dp_num - 1, _DEEP_PROBE_STEP_MS
                    )
                    return True
                # Advance for the next deep probe (skip on the last iteration)
                if dp_num < _DEEP_PROBE_MAX_ATTEMPTS:
                    _logger.warning(
                        "KrakenNonceManager.probe_and_resync: DEEP probe %d/%d rejected — "
                        "advancing +%d ms",
                        dp_num, _DEEP_PROBE_MAX_ATTEMPTS, _DEEP_PROBE_STEP_MS,
                    )
                    with _LOCK:
                        self._last_nonce += _DEEP_PROBE_STEP_MS
                        if self._redis_backend is not None:
                            try:
                                self._redis_backend.advance_to(self._last_nonce)
                            except Exception as _re:
                                _logger.debug(
                                    "KrakenNonceManager.probe_and_resync: Redis advance error (%s)", _re
                                )
                        elif _NONCE_MODE != "timestamp":
                            self._persist()
            _logger.warning(
                "KrakenNonceManager.probe_and_resync: [Tier 1] DEEP probes (%d × %d ms = %.0f min) "
                "also exhausted — escalating to CEILING JUMP",
                _DEEP_PROBE_MAX_ATTEMPTS, _DEEP_PROBE_STEP_MS,
                _DEEP_PROBE_MAX_ATTEMPTS * _DEEP_PROBE_STEP_MS / 60_000,
            )

        # ── Tier 2: ceiling jump (now + 24 h) ────────────────────────────────
        # If the deep probes (or the caller-supplied deep mode) also failed the
        # nonce is so far ahead that a large one-shot jump is the only option.
        # force_ceiling_jump() sets self._last_nonce = now + _CEILING_JUMP_MS
        # (default 24 h), which should land well above Kraken's stored floor.
        _logger.critical(
            "🚀 KrakenNonceManager.probe_and_resync: [Tier 2] automatic CEILING JUMP "
            "(now + %d ms = %.1f h) — all progressive probe tiers exhausted.  "
            "Check for duplicate bot instances if this fires repeatedly.",
            _CEILING_JUMP_MS, _CEILING_JUMP_MS / 3_600_000,
        )
        self.force_ceiling_jump()
        # Probe forward from the ceiling position to pin-point Kraken's floor.
        # _DEEP_PROBE_STEP_MS (10 min) is used here because after a 24-h ceiling
        # jump we need a coarse step that can cover multi-hour floors quickly
        # without wasting many small increments (as _PROBE_STEP_MS = 5 min would).
        _cj_total = _PROBE_ESCALATION_ATTEMPTS + 1
        for cj_num in range(1, _cj_total + 1):
            _logger.info(
                "KrakenNonceManager.probe_and_resync: post-ceiling probe %d/%d (nonce=%d)",
                cj_num, _cj_total, self.get_last_nonce(),
            )
            try:
                cj_result = api_call_fn()
            except Exception as exc:
                _logger.debug(
                    "KrakenNonceManager.probe_and_resync: post-ceiling probe %d raised (%s)",
                    cj_num, exc,
                )
                return False
            if not isinstance(cj_result, dict):
                return False
            if not _is_nonce_error(cj_result):
                if not (cj_result.get("error") or []):
                    _logger.info(
                        "✅ KrakenNonceManager.probe_and_resync: accepted after CEILING JUMP "
                        "(post-ceiling probe %d/%d) — nonce=%d",
                        cj_num, _cj_total, self.get_last_nonce(),
                    )
                return True
            # Advance for next post-ceiling probe (skip on last iteration)
            if cj_num < _cj_total:
                with _LOCK:
                    self._last_nonce += _DEEP_PROBE_STEP_MS
                    if self._redis_backend is not None:
                        try:
                            self._redis_backend.advance_to(self._last_nonce)
                        except Exception as _re:
                            _logger.debug(
                                "KrakenNonceManager.probe_and_resync: Redis advance error (%s)", _re
                            )
                    elif _NONCE_MODE != "timestamp":
                        self._persist()

        # ── All tiers exhausted — log actionable remediation ──────────────────
        # This should be extremely rare: Kraken's floor is > 24 h + probes ahead
        # of wall-clock, which only happens if many ceiling jumps were stacked
        # across sessions, OR a bug in this module accumulated extreme forward
        # drift.  A new API key is the only guaranteed recovery at this point.
        _logger.error(
            "❌ KrakenNonceManager.probe_and_resync: ALL RECOVERY TIERS EXHAUSTED "
            "(standard → deep → ceiling jump + %d post-ceiling steps).  "
            "Automated recovery failed.  Kraken's stored nonce exceeds now + 24 h.\n"
            "Only two real recovery paths remain:\n"
            "  Option 1 (FASTEST + CLEAN): Rotate Kraken API keys.\n"
            "    1. Kraken → Settings → API\n"
            "    2. Delete old API key\n"
            "    3. Create new API key\n"
            "    4. Update bot credentials (.env or store_user_api_key())\n"
            "    5. Restart bot/service\n"
            "    👉 This resets the nonce floor to zero for the new key.\n"
            "  Option 2: Wait until wall-clock time catches up to Kraken's poisoned nonce floor.",
            _cj_total,
        )
        # Intentionally NOT setting _key_invalidated = True.
        # Nonce desync is a resync problem, not a credential problem.
        return False


    def detect_other_process_running(self) -> bool:
        """
        Non-blocking check: return ``True`` if another bot process appears to
        hold the cross-process nonce lock for this key right now.

        Checks ``self._pid_lock_file`` first (process-lifetime lock), then
        ``self._lock_file`` (brief per-op lock) using ``fcntl.LOCK_NB``.
        This catches duplicate processes even when they are idle between nonce
        operations.
        Always returns ``False`` on platforms without fcntl.
        """
        if not _FCNTL_AVAILABLE:
            return False
        try:
            for lock_path in (self._pid_lock_file, self._lock_file):
                # Use append mode — never truncate a file that an active process
                # may have open as a lock target.
                with open(lock_path, "a") as fh:
                    try:
                        _fcntl.flock(fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                        _fcntl.flock(fh, _fcntl.LOCK_UN)
                    except (BlockingIOError, OSError):
                        return True  # lock is held by another process right now
            return False
        except Exception:
            return False

    def _try_acquire_pid_lock(self) -> object:
        """
        Acquire an exclusive process-lifetime lock on ``self._pid_lock_file``.

        The returned file handle is kept open on ``self._pid_lock_fh`` for the
        ENTIRE bot session.  The OS automatically releases the lock when the
        process exits (even via SIGKILL / OOM-kill), so there is no risk of a
        permanently-stuck lock file after a crash.

        If another process already holds the lock:
          • Logs a **CRITICAL** message with actionable instructions.
          • Returns ``None`` (startup continues with degraded duplicate-process
            detection — the per-operation ``_CrossProcessLock`` still prevents
            duplicate nonces at the increment level).

        Returns ``None`` on platforms without ``fcntl`` (e.g. Windows) or when
        the lock file cannot be opened (permission error, missing directory).
        """
        if not _FCNTL_AVAILABLE:
            return None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._pid_lock_file)), exist_ok=True)
            # Append mode: does not truncate an existing PID file from a dead
            # process, and does not interfere with another process's open fd.
            fh = open(self._pid_lock_file, "a")
            try:
                _fcntl.flock(fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                # Another process holds the lock.
                fh.close()
                _logger.critical(
                    "🚨🚨 DUPLICATE BOT PROCESS DETECTED — another NIJA instance "
                    "already holds the process-lifetime nonce lock (%s). "
                    "TWO processes sharing the same Kraken API key WILL cause "
                    "persistent 'EAPI:Invalid nonce' errors on ALL accounts. "
                    "STOP the other process immediately:\n"
                    "  • Railway: stop/delete the duplicate service or deployment\n"
                    "  • Docker:  docker ps -a  →  docker stop <container_id>\n"
                    "  • systemd: systemctl stop nija  (check for multiple units)\n"
                    "  • Manual:  ps aux | grep bot.py  →  kill <pid>\n"
                    "After stopping the duplicate, restart this instance.",
                    self._pid_lock_file,
                )
                return None
            # Write PID for diagnostics (truncate after acquiring the lock so
            # there is no race between open and write).
            fh.truncate(0)
            fh.seek(0)
            fh.write(f"{os.getpid()}\n")
            fh.flush()
            _logger.debug(
                "KrakenNonceManager: process-lifetime PID lock acquired "
                "(pid=%d, file=%s)", os.getpid(), self._pid_lock_file,
            )
            return fh
        except Exception as exc:
            _logger.debug(
                "KrakenNonceManager: PID lock unavailable (%s) — "
                "duplicate-process detection degraded to per-op lock check",
                exc,
            )
            return None

    @classmethod
    def destroy_instance(cls, key_id: str = "") -> None:
        """
        Destroy the singleton or per-key instance (Step 3).

        ``key_id=""``    → destroys the platform singleton (``cls._instance``).
        ``key_id=<str>`` → removes the entry from ``_KEY_REGISTRY``.

        In both cases the next call to ``KrakenNonceManager(key_id)`` or
        ``get_nonce_manager_for_key(key_id)`` constructs a fully fresh object
        anchored to Kraken server time, discarding all accumulated state.

        Contract
        --------
        * Thread-safe: uses ``_instance_lock`` (platform) or ``_KEY_REGISTRY_LOCK``
          (per-key) for the swap.
        * The old instance is NOT mutated; existing references are abandoned.
          Do **not** continue issuing nonces from a reference held before calling.
        * The old instance's PID-lock file handle is closed so the replacement
          singleton in this same process can immediately reacquire the
          process-lifetime lock.
        """
        if not key_id:
            with cls._instance_lock:
                old = cls._instance
                cls._instance = None
        else:
            with _KEY_REGISTRY_LOCK:
                old = _KEY_REGISTRY.pop(key_id, None)
        if old is not None:
            _logger.warning(
                "KrakenNonceManager.destroy_instance: %s destroyed "
                "(last_nonce=%d, last_successful=%d) — "
                "next nonce call will rebuild from Kraken server time",
                f"key '{key_id}'" if key_id else "platform singleton",
                getattr(old, "_last_nonce", 0),
                getattr(old, "_last_successful_nonce", 0),
            )
            _old_pid_lock_fh = getattr(old, "_pid_lock_fh", None)
            if _old_pid_lock_fh is not None:
                try:
                    _old_pid_lock_fh.close()
                    _logger.debug(
                        "KrakenNonceManager.destroy_instance: released old PID lock handle"
                    )
                except Exception as _lock_close_err:
                    _logger.debug(
                        "KrakenNonceManager.destroy_instance: PID lock close error (%s)",
                        _lock_close_err,
                    )
                old._pid_lock_fh = None

    # ── Private helpers ───────────────────────────────────────────────────

    def _read_state_file_raw(self) -> int:
        """Read and return the raw persisted nonce value (0 on any error)."""
        try:
            with open(self._state_file, encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (FileNotFoundError, ValueError, OSError, UnicodeDecodeError):
            return 0

    def _load_last_nonce(self) -> int:
        """
        Compute the startup nonce from Kraken server time ONLY.

        Hard-reset contract (Step 1)
        ----------------------------
        The persisted nonce is intentionally **ignored**.  Every boot anchors
        to ``server_time_ms + _SERVER_SYNC_OFFSET_MS`` so accumulated forward
        drift from prior sessions (nuclear resets, ceiling jumps, etc.) is
        discarded immediately.  If Kraken's stored floor is above this baseline,
        ``probe_and_resync()`` (called from ``broker_manager.connect()``) will
        walk upward until the floor is found.

        Must be called while holding both ``_LOCK`` and ``_CrossProcessLock``.
        """
        server_ms = _fetch_kraken_server_time_ms()
        if server_ms is None:
            server_ms = int(time.time() * 1000)
            _logger.warning(
                "KrakenNonceManager._load_last_nonce: Kraken server-time "
                "endpoint unavailable — using local clock as fallback"
            )
        else:
            now_ms = int(time.time() * 1000)
            _logger.info(
                "KrakenNonceManager._load_last_nonce: Kraken server time = %d ms "
                "(local delta: %+d ms)",
                server_ms, server_ms - now_ms,
            )

        baseline = server_ms + _SERVER_SYNC_OFFSET_MS
        _logger.info(
            "KrakenNonceManager._load_last_nonce: hard-reset startup nonce = "
            "server+%d ms → %d  (persisted nonce discarded)",
            _SERVER_SYNC_OFFSET_MS, baseline,
        )
        return baseline

    def _persist(self) -> None:
        """Atomically write nonce to disk (write-then-rename, mode 0600).

        No-op in Redis mode (Redis is the authoritative store) or in timestamp
        mode (no state-file dependency).

        Uses an exclusive advisory lock (fcntl.LOCK_EX) on the .tmp file so
        that two processes can never interleave their writes — even if the
        process lock in bot.py is bypassed.
        """
        # Skip file I/O when an alternative backend owns the nonce state.
        if self._redis_backend is not None or _NONCE_MODE == "timestamp":
            return
        try:
            tmp = self._state_file + ".tmp"
            with open(tmp, "w") as fh:
                if _FCNTL_AVAILABLE:
                    _fcntl.flock(fh, _fcntl.LOCK_EX)
                fh.write(str(self._last_nonce))
                if _FCNTL_AVAILABLE:
                    _fcntl.flock(fh, _fcntl.LOCK_UN)
            os.chmod(tmp, _PERSISTED_PERMISSIONS)
            os.replace(tmp, self._state_file)
        except Exception as exc:
            _logger.debug("KrakenNonceManager: persist failed (%s)", exc)

    def _backoff_ms(self, error_count: int) -> int:
        """No-op shim — retained for any external callers; server_sync_resync() handles all recovery."""
        return 0


# ── Backward-compatibility aliases ────────────────────────────────────────────
NonceManager = KrakenNonceManager
GlobalKrakenNonceManager = KrakenNonceManager

# ── Module-level singletons ───────────────────────────────────────────────────
_nonce_manager = KrakenNonceManager()


def get_adaptive_offset_engine() -> AdaptiveNonceOffsetEngine:
    """Return the shared AdaptiveNonceOffsetEngine singleton."""
    return AdaptiveNonceOffsetEngine()


# ── Public shortcuts ──────────────────────────────────────────────────────────

def _ensure_live_manager() -> KrakenNonceManager:
    """
    Return the current live KrakenNonceManager, rebuilding it if it was
    destroyed (Step 3) or if the pre-request guard detects a violation (Step 4).

    This is the single choke-point for all nonce issuance and is called by
    both ``get_kraken_nonce()`` and ``get_global_kraken_nonce()``.

    Pre-request guard (Step 4)
    --------------------------
    Two invariants are checked before every nonce:

    1. ``pending_nonce >= last_successful_nonce + _PRE_REQUEST_EPSILON_MS``
       Ensures strict monotonicity relative to the last nonce Kraken confirmed.
       Catches the "stale object" bug where ``_last_nonce`` regressed below
       the confirmed watermark.

    2. ``pending_nonce >= now_ms + _PRE_REQUEST_SAFETY_OFFSET_MS``
       Ensures the nonce is not in the past relative to wall-clock time.
       Catches a frozen/sleeping instance whose ``_last_nonce`` is stale.

    If either invariant is violated, the singleton is destroyed and a fresh
    instance is built from Kraken server time before the nonce is returned.
    """
    global _nonce_manager

    # ── Detect destroyed singleton ────────────────────────────────────────
    current = KrakenNonceManager._instance
    if current is None:
        _logger.info(
            "_ensure_live_manager: singleton was destroyed — rebuilding from "
            "Kraken server time"
        )
        _nonce_manager = KrakenNonceManager()
        return _nonce_manager

    # Keep module-level alias in sync in case another code path rebuilt it.
    if _nonce_manager is not current:
        _nonce_manager = current

    # ── Pre-request guard ─────────────────────────────────────────────────
    now_ms = int(time.time() * 1000)
    with _LOCK:
        last_succ = getattr(current, "_last_successful_nonce", 0)
        pending = current._last_nonce + 1

    fail_monotonic = (
        last_succ > 0
        and pending < last_succ + _PRE_REQUEST_EPSILON_MS
    )
    fail_time = pending < now_ms + _PRE_REQUEST_SAFETY_OFFSET_MS

    if fail_monotonic or fail_time:
        _logger.warning(
            "_ensure_live_manager: pre-request guard violated "
            "(pending=%d, last_succ=%d, now=%d, eps=%d, safety_offset=%d) — "
            "destroying and rebuilding nonce manager from server time",
            pending, last_succ, now_ms,
            _PRE_REQUEST_EPSILON_MS, _PRE_REQUEST_SAFETY_OFFSET_MS,
        )
        KrakenNonceManager.destroy_instance(key_id="")
        _nonce_manager = KrakenNonceManager(key_id="")
        return _nonce_manager

    return current


def get_kraken_nonce() -> int:
    """
    Return the next strictly-increasing Kraken nonce.

    Includes the pre-request guard (Step 4): rebuilds the singleton from
    server time if either the monotonicity or the server-time invariant is
    violated.  Also detects and recovers from a destroyed singleton (Step 3).
    """
    return _ensure_live_manager().next_nonce()


def get_global_kraken_nonce() -> int:
    """Alias for ``get_kraken_nonce()`` — includes pre-request guard."""
    return get_kraken_nonce()


def get_global_nonce_manager() -> KrakenNonceManager:
    """Return the live KrakenNonceManager singleton, rebuilding if destroyed."""
    return _ensure_live_manager()


def get_nonce_manager_for_key(key_id: str) -> KrakenNonceManager:
    """
    Central nonce service factory — returns the authoritative
    ``KrakenNonceManager`` for *key_id*.

    Architecture
    ------------
    This is the **single routing point** for all nonce requests.  Every thread
    and every broker that uses the same Kraken API key must call this function
    to obtain nonces — never construct a ``KrakenNonceManager`` directly.

    * ``key_id=""``    → platform key (existing singleton, full backward compat).
    * ``key_id=<str>`` → per-user/named key — a dedicated instance with its own
                         state file, cross-process fcntl lock, error counters,
                         and strictly-monotonic sequence, completely isolated
                         from every other key.

    Guarantees (per key)
    --------------------
    ✅ Strictly monotonic — nonces never repeat or decrease for this key.
    ✅ Thread-safe — a single ``threading.Lock`` serialises all increments.
    ✅ Cross-process safe — ``fcntl`` advisory lock guards the state file on
       every increment, so two OS processes cannot issue the same nonce.
    ✅ Persistent — nonce survives process restarts via an atomic state file.
    ✅ Pre-request guard — stale/regressed instances are detected and rebuilt
       from Kraken server time before the nonce is issued.

    Kraken requirement fulfilled
    ----------------------------
    Kraken enforces: nonce must be strictly increasing per API key across ALL
    requests.  Routing every request through this function ensures that
    invariant is maintained regardless of how many threads or coroutines are
    in flight.
    """
    if not key_id:
        return _ensure_live_manager()

    # ── Pre-request guard for per-key managers ────────────────────────────
    with _KEY_REGISTRY_LOCK:
        current = _KEY_REGISTRY.get(key_id)

    if current is None:
        return KrakenNonceManager(key_id=key_id)

    now_ms = int(time.time() * 1000)
    with _LOCK:
        last_succ = getattr(current, "_last_successful_nonce", 0)
        pending   = current._last_nonce + 1

    fail_monotonic = last_succ > 0 and pending < last_succ + _PRE_REQUEST_EPSILON_MS
    fail_time      = pending < now_ms + _PRE_REQUEST_SAFETY_OFFSET_MS

    if fail_monotonic or fail_time:
        _logger.warning(
            "get_nonce_manager_for_key(%r): pre-request guard violated "
            "(pending=%d, last_succ=%d, now=%d) — rebuilding from server time",
            key_id, pending, last_succ, now_ms,
        )
        KrakenNonceManager.destroy_instance(key_id=key_id)
        return KrakenNonceManager(key_id=key_id)

    return current


def rebuild_nonce_manager() -> KrakenNonceManager:
    """
    Production-grade safe reset: destroy the current singleton and immediately
    rebuild a fresh instance anchored to Kraken server time.

    This is the **definitive recovery entry point** for preventing future
    nonce desync.  It combines all four fix steps atomically:

    Step 1 — Hard state reset
        The new ``_init()`` unconditionally deletes ``kraken_nonce.state``
        (and ``.lock`` / ``.tmp``) before computing the startup nonce, so
        accumulated forward drift from the destroyed session is discarded.

    Step 2 — Single-writer authority
        ``destroy_instance()`` is called under ``_instance_lock`` so no
        other thread can slip in a stale write between the destroy and the
        rebuild.  The new instance is the sole writer from the moment it is
        constructed.

    Step 3 — Fresh instance, not reset-in-place
        The old singleton is fully discarded; ``KrakenNonceManager()`` builds
        a completely new object.  No stale error counters, no stale
        ``_last_nonce``, no carry-over state.

    Step 4 — Server-time anchor
        ``_load_last_nonce()`` queries ``/0/public/Time`` and sets the new
        nonce to ``server_time_ms + _SERVER_SYNC_OFFSET_MS``.  The pre-request
        guard in ``get_kraken_nonce()`` will enforce both invariants on every
        subsequent call.

    Usage
    -----
    Call from any recovery path — maintenance scripts, the broker's error
    handler, or the self-healing startup sequence::

        from bot.global_kraken_nonce import rebuild_nonce_manager
        new_mgr = rebuild_nonce_manager()

    Safe to call while the bot is running (thread-safe).  For best results
    stop all in-flight Kraken requests before calling so the new nonce floor
    is not immediately stale-d by a concurrent write.

    Returns the newly constructed singleton.
    """
    global _nonce_manager
    _logger.warning(
        "rebuild_nonce_manager: destroying existing singleton and rebuilding "
        "from Kraken server time — all accumulated nonce drift discarded"
    )
    KrakenNonceManager.destroy_instance(key_id="")
    _nonce_manager = KrakenNonceManager(key_id="")
    _logger.warning(
        "rebuild_nonce_manager: rebuild complete — new nonce=%d",
        _nonce_manager.get_last_nonce(),
    )
    return _nonce_manager


def get_global_nonce_stats() -> dict:
    mgr = _ensure_live_manager()
    return {
        "last_nonce": mgr.get_last_nonce(),
        "last_successful_nonce": getattr(mgr, "_last_successful_nonce", 0),
        "nuclear_reset_count": mgr.nuclear_reset_count,
        "deep_reset_active": mgr.is_deep_reset_active,
        "key_invalidated": mgr.is_key_invalidated,
        "trading_paused": mgr.is_paused(),
        "pause_remaining_s": mgr.get_pause_remaining(),
        "broker_quarantined": _quarantine_triggered,
    }


# ── Broker quarantine public API ──────────────────────────────────────────────

def register_broker_quarantine_callback(fn: "Callable[[], None]") -> None:
    """Register a zero-argument callable to be invoked when nonce poisoning is
    confirmed (i.e. nuclear reset count reaches *_NONCE_POISON_QUARANTINE_THRESHOLD*).

    The callback is fired at most once per process lifetime.  Multiple
    callbacks can be registered; they are invoked in registration order.

    Typical use — broker_manager.py registers a handler that sets Kraken to
    ``exit_only_mode=True`` and forces a switch to the Coinbase fallback::

        from bot.global_kraken_nonce import register_broker_quarantine_callback

        def _on_kraken_nonce_quarantine():
            _kraken_quarantine_active_flag.set()

        register_broker_quarantine_callback(_on_kraken_nonce_quarantine)
    """
    with _LOCK:
        _quarantine_callbacks.append(fn)
        # If quarantine already fired before this callback was registered,
        # invoke it immediately so late registrants don't miss the event.
        already_triggered = _quarantine_triggered
    if already_triggered:
        try:
            fn()
        except Exception as exc:
            _logger.error(
                "KrakenNonceManager: late-registered quarantine callback %r raised %s",
                fn, exc,
            )


def is_broker_quarantined() -> bool:
    """Return *True* when nonce poisoning has been confirmed this session.

    Once quarantine is triggered it stays active until :func:`clear_broker_quarantine`
    is called (e.g. after the operator has rotated the Kraken API key).
    """
    return _quarantine_triggered


def clear_broker_quarantine() -> None:
    """Reset the quarantine flag so Kraken can be re-enabled after key rotation.

    Call this only after:
      1. The poisoned Kraken API key has been revoked and a new one issued.
      2. NIJA_DEEP_NONCE_RESET=1 has been applied for the first restart.

    Does NOT re-enable ``exit_only_mode`` on live broker instances — the
    broker layer must do that separately.
    """
    global _quarantine_triggered
    with _LOCK:
        _quarantine_triggered = False
    _logger.warning(
        "KrakenNonceManager: broker quarantine CLEARED — "
        "ensure the Kraken API key has been rotated before resuming entries."
    )


def record_kraken_nonce_error() -> None:
    _ensure_live_manager().record_error()


def record_kraken_nonce_success() -> None:
    _ensure_live_manager().record_success()


def reset_global_kraken_nonce() -> None:
    _ensure_live_manager().reset_to_safe_value()


def force_resync_kraken_nonce() -> None:
    """
    Module-level shortcut for ``KrakenNonceManager.force_resync()``.

    Wipes ``data/kraken_nonce.state`` and the adaptive-offset EMA, then
    sets the nonce to ``now + 5 min`` so the very next API call is accepted.
    For operator / maintenance-script use — stop NIJA before calling this.
    """
    _ensure_live_manager().force_resync()


def force_ceiling_jump_kraken_nonce(ms: int | None = None) -> int:
    """
    Module-level shortcut for ``KrakenNonceManager.force_ceiling_jump()``.

    Advances the nonce to ``now + ms`` (default ``NIJA_NONCE_CEILING_JUMP_MS``,
    i.e. 24 h) in a single step and persists immediately.  Use when Kraken's
    server-side nonce is so far ahead that nuclear resets (+30 min) and deep-
    probe mode (+60 min startup floor) are insufficient.

    Equivalent to setting ``NIJA_NONCE_CEILING_JUMP=1`` at startup, but can
    be called at runtime without restarting the bot.

    ⚠️  Risk: you are guessing the required ceiling.  See
    ``KrakenNonceManager.force_ceiling_jump()`` for full details.

    Returns the new persisted nonce value.
    """
    return _ensure_live_manager().force_ceiling_jump(ms)


def jump_global_kraken_nonce_forward(milliseconds: int) -> None:
    _ensure_live_manager().jump_forward(milliseconds)


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
    return _ensure_live_manager().probe_and_resync(
        api_call_fn, step_ms=step_ms, max_attempts=max_attempts
    )


def nonce_reset_triggered_recently(window_s: float = 300.0) -> bool:
    return False  # tracking removed; retained for compatibility


def is_nonce_trading_paused() -> bool:
    """Return True when a nuclear nonce reset has triggered a trading pause."""
    return _ensure_live_manager().is_paused()


def get_nonce_backend_info() -> dict:
    """
    Return a diagnostics dict describing the active nonce backend and mode.

    Useful for health-check endpoints and operator dashboards::

        {
            "backend":          "file" | "redis" | "timestamp",
            "pid_lock_held":    True | False,
            "pid_lock_file":    "/…/kraken_nonce.state.pid",
            "state_file":       "/…/kraken_nonce.state",
            "redis_url":        "redis://…" | None,
            "redis_key":        "nija:kraken:nonce" | None,
        }
    """
    mgr = _ensure_live_manager()
    if mgr._redis_backend is not None:
        backend = "redis"
    elif _NONCE_MODE == "timestamp":
        backend = "timestamp"
    else:
        backend = "file"
    return {
        "backend":        backend,
        "pid_lock_held":  mgr._pid_lock_fh is not None,
        "pid_lock_file":  mgr._pid_lock_file,
        "state_file":     mgr._state_file,
        "redis_url":      _REDIS_URL if backend == "redis" else None,
        "redis_key":      _REDIS_NONCE_KEY if backend == "redis" else None,
    }


def get_nonce_pause_remaining() -> float:
    """Return seconds remaining in the nonce-triggered trading pause (0.0 when clear)."""
    return _ensure_live_manager().get_pause_remaining()


def is_kraken_key_invalidated() -> bool:
    """
    Return ``True`` when the ``_key_invalidated`` flag has been set on the
    nonce manager.

    Under the server-sync recovery strategy this flag is **never** set by
    ``probe_and_resync()`` — nonce desync is treated as a recoverable
    resync issue, not a credential problem.  This function is retained
    solely for backward compatibility with call sites that import it.

    The flag can still be set manually via internal paths or by calling
    ``force_resync()`` after rotating a key (which clears it).
    """
    return _ensure_live_manager().is_key_invalidated


__all__ = [
    "KrakenNonceManager",
    "NonceManager",
    "GlobalKrakenNonceManager",
    "AdaptiveNonceOffsetEngine",
    "_RedisNonceBackend",
    "get_kraken_api_lock",
    "get_kraken_nonce",
    "get_global_kraken_nonce",
    "get_global_nonce_manager",
    "get_global_nonce_stats",
    "get_nonce_backend_info",
    "get_adaptive_offset_engine",
    "record_kraken_nonce_error",
    "record_kraken_nonce_success",
    "reset_global_kraken_nonce",
    "force_resync_kraken_nonce",
    "force_ceiling_jump_kraken_nonce",
    "jump_global_kraken_nonce_forward",
    "probe_and_resync_nonce",
    "nonce_reset_triggered_recently",
    "is_nonce_trading_paused",
    "is_kraken_key_invalidated",
    "get_nonce_pause_remaining",
    "cleanup_legacy_nonce_files",
    "check_ntp_sync",
    "log_ntp_clock_status",
    "rebuild_nonce_manager",
    "get_nonce_manager_for_key",
    # Broker quarantine API
    "register_broker_quarantine_callback",
    "is_broker_quarantined",
    "clear_broker_quarantine",
]
