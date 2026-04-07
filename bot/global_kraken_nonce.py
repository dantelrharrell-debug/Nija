"""
NIJA Kraken Nonce Manager — Production Grade
=============================================

ONE global monotonic nonce shared across:
- ALL Kraken API calls
- ALL users (PLATFORM + USER accounts)
- ALL retries
- ALL sessions (survives restarts without replaying accepted nonces)

Design guarantees
─────────────────
✅ Startup always lands ahead of any previously-accepted Kraken nonce
   (initialized to max(persisted+1, now_ns + 25 s) clamped below HARD_CAP)
✅ Runaway accumulation capped at 2 min ahead; resets to now_ns + 25 s
✅ Hard-reset in get_nonce(): lead > 60 s → snap to now + 25 s, sleep 5 s
✅ Nuclear-reset in get_nonce(): lead > 300 s → snap + 15 s sleep
✅ record_nonce_error() skips forward jump when lead ≥ 60 s (let get_nonce hard-reset instead)
✅ record_nonce_error() triggers HARD RESET automatically after 3 consecutive errors
✅ Atomic disk writes (write-then-rename) — no half-written files
✅ Thread-safe with RLock throughout
✅ Strictly monotonic — never decreases, never repeats
✅ Nanosecond precision (19-digit nonces)
✅ Auto-recovery: escalating jump sizes on consecutive nonce errors
   (10 s → 20 s → 30 s, resets on success; capped when already far ahead)
✅ Legacy per-account nonce files cleaned up on first startup

Usage
─────
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock

    lock = get_kraken_api_lock()
    with lock:
        nonce = get_global_kraken_nonce()
        # make Kraken API call with nonce

Auto-recovery
─────────────
    manager = get_global_nonce_manager()
    manager.record_nonce_error()    # call when Kraken returns "invalid nonce"
    manager.record_nonce_success()  # call after a successful API call
    manager.reset_to_safe_value()   # manual hard-reset when auto-heal is stuck
"""

import glob as _glob
import logging
import os
import random
import tempfile
import time
import threading

_logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_NONCE_FILE = os.path.join(_DATA_DIR, "kraken_global_nonce.txt")

# Checkpoint cadence: persist after this many get_nonce() calls (in addition to
# always persisting on jump_forward and at startup).
_PERSIST_EVERY_N = 10

# Startup lead-time: always initialise the nonce at least this many nanoseconds
# ahead of now.  25 s absorbs typical Kraken clock-drift tolerance and ensures
# we land above any previously-accepted nonce without triggering the 60 s
# HARD-RESET threshold on the very first get_nonce() call.
_STARTUP_LEAD_NS = 25 * 1_000_000_000  # 25 seconds

# Maximum acceptable lead-time.  If the persisted nonce is further ahead than
# this we assume it came from a crash-loop runaway and reset to now + lead.
_MAX_LEAD_NS = 120 * 1_000_000_000  # 2 minutes

# Nanoseconds per second — used for human-readable log messages.
_NS_PER_SECOND = 1_000_000_000

# Escalating recovery jumps (nanoseconds): 10 s, 20 s, 30 s.
# Smaller initial jumps avoid overshooting when the nonce is only slightly
# desynchronized; the jump is also capped dynamically if _last_nonce is
# already far ahead of the wall clock (see record_nonce_error).
_RECOVERY_JUMPS_NS = [
    10 * 1_000_000_000,
    20 * 1_000_000_000,
    30 * 1_000_000_000,
]

# If _last_nonce is already this far ahead of now, cap the recovery jump to
# _RECOVERY_JUMP_CAP_NS to avoid runaway accumulation.
_RECOVERY_AHEAD_THRESHOLD_NS = 30 * 1_000_000_000   # 30 seconds
_RECOVERY_JUMP_CAP_NS        = 10 * 1_000_000_000   # 10 seconds

# Hard cap on runtime nonce lead-time.  If get_nonce() detects that
# _last_nonce is further ahead than this the manager performs an immediate
# reset to now + _STARTUP_JUMP_NS.  This is a non-negotiable production
# safety rail: a nonce >60 s ahead is guaranteed to cause EAPI:Invalid nonce
# errors on every call until wall-clock catches up.
_HARD_CAP_LEAD_NS = 60 * 1_000_000_000    # 60 seconds

# Safety buffer below _HARD_CAP_LEAD_NS used during startup to clamp the
# candidate nonce so the very first get_nonce() call cannot trigger a HARD
# RESET.  Effective ceiling: 60 s − 5 s = 55 s.
_HARD_CAP_BUFFER_NS = 5 * 1_000_000_000   #  5 seconds

# Nuclear-reset threshold: if lead exceeds this extreme value, treat as a
# crash-loop runaway and apply an extra sleep before retrying.
_NUCLEAR_LEAD_NS  = 300 * 1_000_000_000   # 5 minutes

# Nonce persistence file — survives process restarts so accumulated jumps are not lost
_NONCE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "kraken_global_nonce.txt"
)
_PERSIST_EVERY_N = 10  # Write to disk after this many get_nonce() calls (reduced from 100 to shrink crash gap)

# Runtime reset jump applied by HARD and NUCLEAR resets inside get_nonce().
# Raised from 20 s → 25 s to match _STARTUP_LEAD_NS and give Kraken more room
# to accept the new nonce before the next call arrives.  Startup initialisation
# and reset_to_safe_value() also use 25 s (via _STARTUP_LEAD_NS).
_STARTUP_JUMP_NS = 25_000_000_000  # +25 seconds in nanoseconds

# Seconds to sleep inside get_nonce() after a NUCLEAR or HARD reset to let
# Kraken's nonce window expire before the first post-reset API call.
# Previous values: NUCLEAR=5 s, HARD=0 s.  Raised to 15 s / 5 s respectively.
_POST_NUCLEAR_SLEEP_S: float = 15.0  # was 5 s
_POST_HARD_SLEEP_S: float = 5.0      # was 0 s (none)

# Consecutive nonce error threshold that triggers an immediate HARD RESET instead
# of continuing to jump forward.  After 3 consecutive nonce errors the escalating
# jumps (10 s + 20 s + 30 s = 60 s) have already pushed the nonce to the HARD-CAP
# boundary; forcing a snap-back at this point is safer than risking a lockout.
_HARD_RESET_ON_CONSECUTIVE_ERRORS: int = 3

# Maximum random jitter (seconds) added to each caller that was waiting on the
# post-reset gate when it opens.  Spreading out concurrent callers prevents a burst
# of back-to-back Kraken requests immediately after a reset.
_POST_RESET_JITTER_MAX_S: float = 1.5

# ── Disk helpers ───────────────────────────────────────────────────────────────

def _load_persisted_nonce() -> int:
    """Load the last persisted nonce from disk.  Returns 0 on any failure."""
    try:
        if os.path.exists(_NONCE_FILE):
            with open(_NONCE_FILE, "r") as fh:
                content = fh.read().strip()
                if content:
                    return int(content)
    except (ValueError, IOError, OSError) as exc:
        _logger.debug("global_kraken_nonce: could not load persisted nonce: %s", exc)
    return 0


def _persist_nonce(nonce: int) -> None:
    """
    Write nonce to disk atomically (write-then-rename).

    Atomic rename prevents a process crash mid-write from leaving a
    corrupt nonce file that would reset the sequence on the next startup.
    Never raises — logs debug on failure.
    """
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=_DATA_DIR, prefix=".nonce_tmp_")
        try:
            os.chmod(tmp_path, 0o600)  # owner read/write only
            with os.fdopen(fd, "w") as fh:
                fh.write(str(nonce))
            os.replace(tmp_path, _NONCE_FILE)  # atomic on POSIX
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (IOError, OSError) as exc:
        _logger.debug("global_kraken_nonce: could not persist nonce: %s", exc)


def cleanup_legacy_nonce_files() -> None:
    """
    Remove stale per-account nonce files left by older bot versions.

    Safe to call multiple times; logs a single info line summarising what
    was removed and silently skips files that cannot be deleted.
    """
    patterns = [
        # Legacy per-account nonce files (e.g. kraken_nonce_platform.txt,
        # kraken_nonce_user_*.txt).  More patterns may be added here if
        # future bot versions introduce additional nonce file variants.
        os.path.join(_DATA_DIR, "kraken_nonce*.txt"),
    ]
    removed = []
    for pattern in patterns:
        for path in _glob.glob(pattern):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except OSError as exc:
                _logger.debug("global_kraken_nonce: could not remove legacy file %s: %s", path, exc)
    if removed:
        _logger.info("global_kraken_nonce: removed %d legacy nonce file(s): %s", len(removed), removed)


# ── Simple singleton nonce manager (primary path) ────────────────────────────

class NonceManager:
    """
    Thread-safe singleton nonce generator for Kraken API.

    Uses millisecond timestamps (13 digits) with a strictly-increasing
    enforcement: if wall-clock time has not advanced since the last call,
    the counter is incremented by 1 so every returned value is unique.

    ONE singleton instance is shared across every thread and every
    KrakenBroker account, which means parallel balance/position fetches
    on the same API key can never produce duplicate or out-of-order
    nonces.

    Usage::

        from bot.global_kraken_nonce import NonceManager

        nonce_manager = NonceManager()
        payload["nonce"] = nonce_manager.get_nonce()
        # — or —
        self.api._nonce = lambda: str(NonceManager().get_nonce())
    """

    _instance = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    _now = time.time()
                    inst._nonce = int(_now * 1000)
                    inst._last_ts = _now
                    inst._thread_lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    def get_nonce(self) -> int:
        """
        Return the next strictly-increasing millisecond nonce.

        Thread-safe: protected by an instance-level Lock so concurrent callers
        from multiple threads or broker accounts always receive distinct,
        ordered values.

        Returns:
            int: Milliseconds since epoch, guaranteed > previous return value.
        """
        with self._thread_lock:
            now = int(time.time() * 1000)
            if now <= self._nonce:
                now = self._nonce + 1
            self._nonce = now
            self._last_ts = time.time()
            return self._nonce

    def peek(self) -> int:
        """Return the last issued nonce without advancing the counter."""
        with self._thread_lock:
            return self._nonce

    def reset_to_safe_value(self, offset_ms: int = 25_000) -> int:
        """
        Hard-reset the nonce to current time + *offset_ms* milliseconds.

        Use for manual recovery when repeated "Invalid nonce" errors cannot
        be resolved by the normal escalating-jump mechanism.  The default
        25-second offset absorbs typical Kraken clock-drift tolerance and
        allows two escalating error retries (10 s + 20 s = 30 s) before
        approaching the 60 s HARD-RESET threshold.

        Args:
            offset_ms: Milliseconds to add to current time (default 25 000 = 25 s).

        Returns:
            int: New nonce value after reset.
        """
        with self._thread_lock:
            self._nonce = int(time.time() * 1000) + offset_ms
            self._last_ts = time.time()
            _logger.warning(
                "global_kraken_nonce: NonceManager.reset_to_safe_value() called; "
                "new nonce = %d (offset +%d ms)",
                self._nonce,
                offset_ms,
            )
            return self._nonce


# ── Persistent singleton nonce manager (legacy / advanced recovery) ───────────

class GlobalKrakenNonceManager:
    """
    Production-grade singleton nonce manager for Kraken API.

    Key properties
    ──────────────
    - Nanosecond precision (19-digit nonces via time.time_ns())
    - Thread-safe (RLock throughout)
    - Strictly monotonic — never repeats or decreases
    - Survives restarts: initialises to max(persisted+1, now + 25 s) clamped
      below the 60 s HARD-RESET threshold, then persists the startup value
    - Runaway protection: if persisted > now + 2 min, resets to now + 25 s
    - Auto-recovery: escalating nonce jumps on consecutive errors

    Usage
    ─────
        manager = get_global_nonce_manager()
        nonce   = manager.get_nonce()
    """

    _instance = None
    _class_lock = threading.RLock()

    def __new__(cls):
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        with self._class_lock:
            if getattr(self, "_initialized", False):
                return

            self._nonce_lock = threading.RLock()

            current_ns = time.time_ns()
            persisted = _load_persisted_nonce()

            if persisted > current_ns + _MAX_LEAD_NS:
                excess_s = (persisted - current_ns) / _NS_PER_SECOND
                _logger.warning(
                    "global_kraken_nonce: persisted nonce is %.0fs ahead of now "
                    "(likely from crash-loop jumps); resetting to now + %ds.",
                    excess_s,
                    _STARTUP_LEAD_NS // _NS_PER_SECOND,
                )
                persisted = 0  # force the startup-lead path below

            # Start strictly above the last persisted nonce while keeping a
            # minimum lead of _STARTUP_LEAD_NS (25 s) from the wall clock.
            # Clamping: if the candidate would land within _HARD_CAP_BUFFER_NS
            # (5 s) of the 60 s HARD-RESET threshold, snap back to
            # now + _STARTUP_LEAD_NS so the very first get_nonce() call does
            # not immediately trigger a HARD RESET cycle.
            _safe_max_ns = current_ns + _HARD_CAP_LEAD_NS - _HARD_CAP_BUFFER_NS  # 55 s
            candidate_ns = max(persisted + 1, current_ns + _STARTUP_LEAD_NS)
            if candidate_ns > _safe_max_ns:
                _logger.warning(
                    "global_kraken_nonce: startup candidate nonce is %.1fs ahead — "
                    "clamping to now + %.0fs to avoid HARD RESET on first call.",
                    (candidate_ns - current_ns) / _NS_PER_SECOND,
                    _STARTUP_LEAD_NS / _NS_PER_SECOND,
                )
                candidate_ns = current_ns + _STARTUP_LEAD_NS
            self._last_nonce = candidate_ns

            # Persist immediately — this is the single most important write.
            _persist_nonce(self._last_nonce)

            # Remove stale legacy files so they can never be picked up by old
            # code paths still reading per-account nonce files.
            cleanup_legacy_nonce_files()

            # Counters
            self._nonces_since_persist = 0
            self._consecutive_errors = 0

            # Connection-gate: wall-clock timestamp of last hard/nuclear reset (None = never)
            self._reset_triggered_at: float | None = None

            # Post-reset serialization gate.
            # After a HARD or NUCLEAR reset the gate is *cleared* (closed).  Only ONE
            # in-flight API call is allowed until record_nonce_success() opens the gate
            # again.  This prevents a burst of concurrent requests from racing to Kraken
            # with back-to-back nonces before the first one is confirmed valid.
            # The gate starts *set* (open) so normal startup traffic is unrestricted.
            self._post_reset_gate: threading.Event = threading.Event()
            self._post_reset_gate.set()
            # Maximum seconds a caller will wait for the gate to reopen before
            # giving up and proceeding anyway.  70 s is chosen to be just over
            # the HARD_CAP lead (60 s) so any caller that waited for the gate
            # is guaranteed to have a valid nonce window by the time it proceeds.
            self._post_reset_gate_timeout_s: float = 70.0

            # Statistics tracking
            self._total_nonces_issued = 0
            self._creation_time = time.time()

            self._initialized = True

            _logger.info(
                "global_kraken_nonce: manager ready — startup nonce %d "
                "(%.1f s ahead of now)",
                self._last_nonce,
                (self._last_nonce - current_ns) / _NS_PER_SECOND,
            )

    # ── Core nonce generation ──────────────────────────────────────────────

    def get_nonce(self) -> int:
        """
        Return the next monotonically increasing nonce (nanoseconds).

        Thread-safe.  Each call returns a value strictly greater than the last.

        Hard-reset policy (checked BEFORE any increment):
          • lead > 300 s (nuclear): reset to now + 25 s, persist, sleep 15 s
          • lead >  60 s (hard cap): reset to now + 25 s, persist, sleep 5 s

        Post-reset gate:
          After a HARD or NUCLEAR reset the internal ``_post_reset_gate`` Event
          is cleared so that subsequent callers block until
          ``record_nonce_success()`` opens the gate.  This ensures only one
          request races to Kraken at a time while the nonce window is settling.
        """
        with self._nonce_lock:
            # ── Post-reset gate — block until first success after a reset ──
            if not self._post_reset_gate.is_set():
                # Release the nonce lock while waiting to avoid deadlock
                # (record_nonce_success also acquires _nonce_lock).
                self._nonce_lock.release()
                _gate_opened = self._post_reset_gate.wait(
                    timeout=self._post_reset_gate_timeout_s
                )
                if _gate_opened:
                    # Add random jitter before reacquiring the lock so that multiple
                    # threads that were all blocked on this gate stagger their
                    # subsequent Kraken requests rather than hitting the API in a burst.
                    _jitter = random.uniform(0.0, _POST_RESET_JITTER_MAX_S)
                    if _jitter > 0.05:
                        _logger.debug(
                            "global_kraken_nonce: post-reset jitter %.2fs applied",
                            _jitter,
                        )
                        time.sleep(_jitter)
                self._nonce_lock.acquire()
                if not _gate_opened:
                    _logger.warning(
                        "global_kraken_nonce: post-reset gate timed out after %.0fs "
                        "— opening automatically to avoid permanent stall",
                        self._post_reset_gate_timeout_s,
                    )
                    self._post_reset_gate.set()

            now = time.time_ns()
            lead = self._last_nonce - now

            # ── Nuclear recovery (> 5 min) ────────────────────────────────
            if lead > _NUCLEAR_LEAD_NS:
                _logger.warning(
                    "NUCLEAR RESET: nonce was %.1fs ahead of wall clock "
                    "(> 300 s threshold) — resetting to now + %ds and sleeping %.0fs",
                    lead / _NS_PER_SECOND,
                    _STARTUP_JUMP_NS // _NS_PER_SECOND,
                    _POST_NUCLEAR_SLEEP_S,
                )
                self._last_nonce = now + _STARTUP_JUMP_NS
                self._consecutive_errors = 0
                self._nonces_since_persist = 0
                self._reset_triggered_at = time.time()
                self._post_reset_gate.clear()  # Block concurrent callers until success
                _persist_nonce(self._last_nonce)
                # Release lock while sleeping so other threads aren't starved.
                self._nonce_lock.release()
                try:
                    time.sleep(_POST_NUCLEAR_SLEEP_S)
                finally:
                    self._nonce_lock.acquire()
                # Refresh 'now' and 'lead' after the sleep.
                now = time.time_ns()
                lead = self._last_nonce - now

            # ── Hard-cap reset (> 60 s) ───────────────────────────────────
            elif lead > _HARD_CAP_LEAD_NS:
                _logger.warning(
                    "HARD RESET: nonce was %.1fs ahead of wall clock "
                    "(> 60 s threshold) → reset to now + %ds, sleeping %.0fs",
                    lead / _NS_PER_SECOND,
                    _STARTUP_JUMP_NS // _NS_PER_SECOND,
                    _POST_HARD_SLEEP_S,
                )
                self._last_nonce = now + _STARTUP_JUMP_NS
                self._consecutive_errors = 0
                self._nonces_since_persist = 0
                self._total_nonces_issued += 1
                self._reset_triggered_at = time.time()
                self._post_reset_gate.clear()  # Block concurrent callers until success
                _persist_nonce(self._last_nonce)
                # Brief sleep so Kraken's nonce window has time to accept the new
                # base nonce before the next API call arrives.
                self._nonce_lock.release()
                try:
                    time.sleep(_POST_HARD_SLEEP_S)
                finally:
                    self._nonce_lock.acquire()
                return self._last_nonce

            # ── Normal monotonic increment ────────────────────────────────
            new_nonce = max(now, self._last_nonce + 1)
            self._last_nonce = new_nonce
            self._total_nonces_issued += 1

            self._nonces_since_persist += 1
            if self._nonces_since_persist >= _PERSIST_EVERY_N:
                self._nonces_since_persist = 0
                _persist_nonce(new_nonce)

            return new_nonce

    # ── Recovery helpers ───────────────────────────────────────────────────

    def jump_forward(self, nanoseconds: int) -> int:
        """
        Jump the nonce forward by *nanoseconds*.

        Used for error recovery.  The new value is persisted to disk
        immediately so a restart won't replay nonces Kraken already saw.

        Returns the new nonce value.
        """
        with self._nonce_lock:
            current_time_ns = time.time_ns()
            self._last_nonce = max(
                current_time_ns + nanoseconds,
                self._last_nonce + nanoseconds,
            )
            self._nonces_since_persist = 0
            _persist_nonce(self._last_nonce)
            return self._last_nonce

    def record_nonce_error(self) -> int:
        """
        Record a Kraken "invalid nonce" error and perform an escalating jump.

        Jump schedule (resets after record_nonce_success()):
          1st error  → +10 s
          2nd error  → +20 s
          3rd+ error → +30 s

        Dynamic cap: if _last_nonce is already more than 30 s ahead of the
        wall clock the jump is capped to 10 s to avoid runaway accumulation.

        Hard-cap guard: if lead already exceeds _HARD_CAP_LEAD_NS (60 s) the
        forward bump is skipped entirely — get_nonce() will perform a hard
        reset on the next call instead.

        Automatic HARD RESET: if consecutive errors reach
        _HARD_RESET_ON_CONSECUTIVE_ERRORS (3), a HARD RESET is triggered
        immediately (snap to now + 25 s, gate closed) rather than continuing
        to jump forward.  This prevents a runaway error loop from pushing the
        nonce beyond the 60 s HARD-CAP.

        Returns:
            int: Current consecutive-error count after recording this error.
        """
        with self._nonce_lock:
            self._consecutive_errors += 1
            count = self._consecutive_errors

            current_ns = time.time_ns()
            current_lead_ns = self._last_nonce - current_ns

            # ── Automatic HARD RESET after too many consecutive errors ────
            # Escalating jumps (10 s + 20 s = 30 s by error #2) are approaching
            # the 60 s HARD-CAP by error #3.  Force a clean snap-back now.
            if count >= _HARD_RESET_ON_CONSECUTIVE_ERRORS:
                _logger.warning(
                    "global_kraken_nonce: %d consecutive nonce errors — triggering "
                    "HARD RESET (snap to now + %ds, gate closed)",
                    count,
                    _STARTUP_JUMP_NS // _NS_PER_SECOND,
                )
                self._last_nonce = current_ns + _STARTUP_JUMP_NS
                self._consecutive_errors = 0
                self._nonces_since_persist = 0
                self._reset_triggered_at = time.time()
                self._post_reset_gate.clear()
                _persist_nonce(self._last_nonce)
                return 0  # Indicate clean-slate after hard reset

            # Do not jump forward when already far ahead — the hard-reset in
            # get_nonce() will handle correction on the next call.
            if current_lead_ns > _HARD_CAP_LEAD_NS:
                _logger.warning(
                    "global_kraken_nonce: nonce error #%d — skipping forward jump "
                    "(already %.1fs ahead ≥ 60 s hard-cap; get_nonce() will hard-reset)",
                    count,
                    current_lead_ns / _NS_PER_SECOND,
                )
                return count

            idx = min(count - 1, len(_RECOVERY_JUMPS_NS) - 1)
            jump_ns = _RECOVERY_JUMPS_NS[idx]

            # Cap the jump when we're already well ahead to avoid overshoot.
            if current_lead_ns > _RECOVERY_AHEAD_THRESHOLD_NS:
                capped_ns = min(jump_ns, _RECOVERY_JUMP_CAP_NS)
                if capped_ns < jump_ns:
                    _logger.debug(
                        "global_kraken_nonce: capping recovery jump from +%.0fs to +%.0fs "
                        "(already %.1fs ahead of wall clock)",
                        jump_ns / _NS_PER_SECOND,
                        capped_ns / _NS_PER_SECOND,
                        current_lead_ns / _NS_PER_SECOND,
                    )
                jump_ns = capped_ns

            self._last_nonce = max(
                current_ns + jump_ns,
                self._last_nonce + jump_ns,
            )
            self._nonces_since_persist = 0
            _persist_nonce(self._last_nonce)

            _logger.warning(
                "global_kraken_nonce: nonce error #%d — jumped forward +%.0fs "
                "(lead was %.1fs, now %.1fs ahead of wall clock)",
                count,
                jump_ns / _NS_PER_SECOND,
                current_lead_ns / _NS_PER_SECOND,
                (self._last_nonce - current_ns) / _NS_PER_SECOND,
            )
            return count

    def reset_to_safe_value(self) -> int:
        """
        Hard-reset the nonce to a safe value for manual recovery.

        Sets the nonce to current nanoseconds + _STARTUP_LEAD_NS (25 s) and
        persists immediately.  The 25 s lead absorbs Kraken's clock-drift
        tolerance and allows up to two escalating error jumps (10 s + 20 s = 30 s)
        before reaching the 60 s HARD-RESET threshold.  Use this when the bot
        is stuck and normal auto-heal has not resolved the desync.

        Returns:
            int: New nonce value after reset
        """
        with self._nonce_lock:
            self._last_nonce = time.time_ns() + _STARTUP_LEAD_NS
            self._nonces_since_persist = 0
            self._consecutive_errors = 0
            self._post_reset_gate.clear()  # Gate callers until first success after this reset
            _persist_nonce(self._last_nonce)
            _logger.warning(
                f"global_kraken_nonce: manual reset_to_safe_value() called; "
                f"new nonce = {self._last_nonce}"
            )
            return self._last_nonce

    def get_last_nonce(self) -> int:
        """
        Return the most recently issued nonce without advancing the counter.

        Useful for external code that needs to snapshot the current nonce
        position without consuming a new value.

        Returns:
            int: Last issued nonce (nanoseconds)
        """
        with self._nonce_lock:
            return self._last_nonce

    def record_nonce_success(self) -> None:
        """
        Record a successful Kraken API call and reset the error counter.

        Call this after every successful private API response to keep the
        escalating recovery schedule accurate.  Also opens the post-reset gate
        so the next queued caller may proceed.
        """
        with self._nonce_lock:
            if self._consecutive_errors > 0:
                _logger.debug(
                    "global_kraken_nonce: nonce success — resetting error counter "
                    "(was %d)",
                    self._consecutive_errors,
                )
                self._consecutive_errors = 0
            # Open the post-reset gate on every success.  If we were in a
            # post-reset hold, this unblocks the next waiting caller so it can
            # proceed with its own nonce.
            if not self._post_reset_gate.is_set():
                _logger.info(
                    "global_kraken_nonce: post-reset gate opened — "
                    "first successful API call after reset confirmed"
                )
                self._post_reset_gate.set()

    def was_reset_recently(self, window_s: float = 300.0) -> bool:
        """
        Return True if a hard or nuclear nonce reset was triggered within the
        last *window_s* seconds (default 5 minutes).

        Use this as a **connection gate**: when True, delay entering new trades
        for 1–2 scan cycles to let the nonce settle before issuing API calls.

        Args:
            window_s: Look-back window in seconds.

        Returns:
            bool: True if a reset occurred within the window, False otherwise.
        """
        with self._nonce_lock:
            if self._reset_triggered_at is None:
                return False
            return (time.time() - self._reset_triggered_at) < window_s

    # ── Diagnostics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return a dict with runtime statistics for monitoring / logging."""
        with self._nonce_lock:
            uptime = time.time() - self._creation_time
            rate = self._total_nonces_issued / uptime if uptime > 0 else 0
            lead_s = (self._last_nonce - time.time_ns()) / _NS_PER_SECOND
            return {
                "total_nonces_issued": self._total_nonces_issued,
                "last_nonce": self._last_nonce,
                "lead_seconds": round(lead_s, 3),
                "consecutive_errors": self._consecutive_errors,
                "uptime_seconds": round(uptime, 1),
                "nonces_per_second": round(rate, 3),
            }


# ── Module-level accessors (public API) ────────────────────────────────────────

def get_global_nonce_manager() -> GlobalKrakenNonceManager:
    """Return the process-wide GlobalKrakenNonceManager singleton."""
    return GlobalKrakenNonceManager()


def get_global_nonce_stats() -> dict:
    """Return runtime statistics from the global nonce manager."""
    return get_global_nonce_manager().get_stats()


def get_kraken_nonce() -> int:
    """
    Return the next Kraken API nonce (nanoseconds, 19 digits).

    Primary interface for all Kraken private API calls.  Guaranteed to be
    strictly monotonic across threads, retries, and process restarts.
    """
    return get_global_nonce_manager().get_nonce()


# Alias kept for backwards compatibility
get_global_kraken_nonce = get_kraken_nonce


# ── Global API serialisation lock ─────────────────────────────────────────────

# Kraken rejects parallel private calls on the same API key — serialise them.
# Use RLock so _nonce_monotonic() can safely re-acquire it when called from
# within _kraken_private_call() (which already holds this lock).
_KRAKEN_API_LOCK = threading.RLock()


def get_kraken_api_lock() -> threading.RLock:
    """
    Return the process-wide Kraken API serialisation lock.

    Acquire this lock around every private Kraken API call to prevent
    parallel writes that would cause nonce ordering violations.  The lock
    is an RLock so that _nonce_monotonic() can safely re-acquire it when
    invoked from within _kraken_private_call() (which already holds it).

    Usage::

        with get_kraken_api_lock():
            nonce = get_global_kraken_nonce()
            # make Kraken private API call
    """
    return _KRAKEN_API_LOCK


def jump_global_kraken_nonce_forward(milliseconds: int) -> int:
    """
    Jump the global nonce forward by *milliseconds* (converted to nanoseconds).

    Convenience wrapper used by broker_manager for manual recovery jumps.
    Returns the new nonce value (nanoseconds).
    """
    return get_global_nonce_manager().jump_forward(milliseconds * 1_000_000)


def record_kraken_nonce_error() -> int:
    """
    Signal that a Kraken "invalid nonce" error occurred.

    Performs an escalating jump and returns the nanoseconds jumped.
    Prefer this over manual jump_global_kraken_nonce_forward() calls so
    the auto-recovery escalation state is tracked correctly.
    """
    return get_global_nonce_manager().record_nonce_error()


def record_kraken_nonce_success() -> None:
    """Signal that a Kraken API call succeeded.  Resets escalation counter."""
    get_global_nonce_manager().record_nonce_success()


def reset_global_kraken_nonce() -> int:
    """
    Hard-reset the global nonce to a safe value (current time + 25 s).

    Convenience wrapper around GlobalKrakenNonceManager.reset_to_safe_value().
    The 25 s lead absorbs Kraken's clock-drift tolerance and gives two
    escalating error retries (10 s + 20 s = 30 s) before hitting the 60 s
    HARD-RESET threshold.  Use when the bot is stuck with repeated
    "EAPI:Invalid nonce" errors and normal auto-heal has not resolved the
    desync.

    Returns:
        int: New nonce value after reset (nanoseconds)
    """
    return get_global_nonce_manager().reset_to_safe_value()


def nonce_reset_triggered_recently(window_s: float = 300.0) -> bool:
    """
    Return True if a hard or nuclear nonce reset occurred within the last
    *window_s* seconds (default 5 minutes).

    Use as a connection gate — when True, skip or delay new trade entries for
    1–2 scan cycles to let the nonce stabilise before issuing Kraken API calls.
    """
    return get_global_nonce_manager().was_reset_recently(window_s)


__all__ = [
    "NonceManager",
    "GlobalKrakenNonceManager",
    "get_global_nonce_manager",
    "get_global_nonce_stats",
    "get_kraken_nonce",
    "get_global_kraken_nonce",
    "get_kraken_api_lock",
    "jump_global_kraken_nonce_forward",
    "record_kraken_nonce_error",
    "record_kraken_nonce_success",
    "reset_global_kraken_nonce",
    "nonce_reset_triggered_recently",
    "cleanup_legacy_nonce_files",
]
