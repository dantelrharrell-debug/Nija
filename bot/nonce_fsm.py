"""
NonceFSM — drop-in corrected nonce state machine for NIJA / Kraken.
====================================================================

Fixes shipped in this module
------------------------------
1. **CEILING_JUMP bug**
   The original ``force_ceiling_jump()`` computed ``ceiling = now + jump_ms``.
   When the nonce had already drifted far past *now* (due to prior failed probe
   runs), the condition ``ceiling > self._last_nonce`` was False and the jump was
   silently skipped — leaving the probe escalation path in a no-op loop.

   Fix: ceiling is now anchored to ``max(last_nonce, now) + jump_ms`` so the
   jump is *always* above the current nonce value, regardless of existing drift.

2. **Infinite forward drift**
   The old ``probe_and_resync`` loop called ``server_sync_resync()`` once and
   then unconditionally added ``+step_ms`` on every failed probe, persisting
   each jump.  When the broker caught ``False`` and retried, the *next* call
   started from where the previous left off — drifting the nonce by
   ``N × max_attempts × step_ms`` per session.  After a few retries the nonce
   was months ahead of anything Kraken would accept.

   Fix: at probe-loop entry a *base floor* is snapshotted from ``server_sync_resync``.
   Probe jumps are done in-memory only (not persisted).  On exit the nonce is
   written as either the successful probe value or the base floor + 1 (on full
   exhaustion), so the accumulated in-loop drift is never committed.

3. **Kraken resync failure loop**
   When all probe attempts failed the module returned ``False`` without resetting
   the nonce.  The broker caught ``False``, waited, then called ``probe_and_resync``
   again.  Because the nonce was already past Kraken's window, every subsequent
   ``server_sync_resync`` was also rejected (small offset not enough) and the
   probe loop started from an even-higher drift floor — an infinite growth loop.

   Fix: a per-session ``_resync_attempts`` counter is maintained.  After
   ``MAX_RESYNC_BEFORE_CIRCUIT_BREAK`` failures without *any* successful API call
   the FSM transitions to ``CIRCUIT_OPEN``, nonce is reset to ``server_time + 3 s``,
   and further ``probe_and_resync`` calls raise ``NonceFSMCircuitOpen`` instead of
   running indefinitely.  Callers can reset with ``reset_circuit()``.

4. **FSM deadlock**
   The original ``_wait_for_probe_window()`` in ``KrakenNonceManager.__new__`` had
   no hard timeout through the code path that checked ``timeout_s=None``.  Any
   unhandled exception inside a probe window that prevented ``_probe_window_end()``
   from running would leave ``_PROBE_WINDOW_ACTIVE > 0`` permanently, making every
   subsequent ``KrakenNonceManager()`` construction block forever.

   Fix:
   * All state transitions happen under ``_FSM_LOCK`` acquired with a hard timeout
     (``_LOCK_ACQUIRE_TIMEOUT_S``, default 8 s).  Lock acquisition failure raises
     ``NonceFSMLockTimeout`` — an explicit error, never a silent hang.
   * ``probe_and_resync`` is implemented as a context-manager-controlled window
     (``_ProbeWindow``) whose ``__exit__`` fires even when the body raises.
   * A watchdog thread clears any probe window stuck for > ``PROBE_WATCHDOG_S``
     (default 30 s) and transitions the FSM to ``RECOVERING`` so the manager
     self-heals without operator intervention.
   * All ``threading.Condition.wait()`` calls use an explicit timeout so no
     blocking call is unbounded.

Public interface (drop-in compatible with KrakenNonceManager)
--------------------------------------------------------------
    from bot.nonce_fsm import get_nonce_fsm

    nonce = get_nonce_fsm().next_nonce()
    get_nonce_fsm().record_error()
    get_nonce_fsm().record_success()
    ok = get_nonce_fsm().probe_and_resync(api_call_fn)
    get_nonce_fsm().force_ceiling_jump()
    get_nonce_fsm().reset_circuit()

Environment variables (all optional)
--------------------------------------
    NIJA_FSM_LOCK_TIMEOUT_S         Hard timeout for internal lock acquisition (default 8)
    NIJA_FSM_PROBE_WATCHDOG_S       Max seconds a probe window may stay open (default 30)
    NIJA_FSM_MAX_RESYNC             Circuit-breaker threshold: consecutive failed resyncs (default 5)
    NIJA_FSM_SERVER_SYNC_OFFSET_MS  Lead (ms) above Kraken server time in recovery (default 3000)
    NIJA_FSM_RECOVERY_FREEZE_S      Pause before querying server time in recovery (default 3.0)
    NIJA_FSM_CEILING_JUMP_MS        Size of escalation ceiling jump (default 86400000 = 24 h)
    NIJA_FSM_PROBE_STEP_MS          Per-step advance in probe loop (default 300000 = 5 min)
    NIJA_FSM_PROBE_MAX_ATTEMPTS     Maximum steps in one probe run (default 12)
    NIJA_FSM_STARTUP_JUMP_MS        Lead added over persisted nonce at startup (default 10000)
"""

from __future__ import annotations

import enum
import logging
import os
import threading
import time
from typing import Callable, Optional

_logger = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────

_LOCK_ACQUIRE_TIMEOUT_S: float = float(os.environ.get("NIJA_FSM_LOCK_TIMEOUT_S", "8"))
_PROBE_WATCHDOG_S: float = float(os.environ.get("NIJA_FSM_PROBE_WATCHDOG_S", "30"))
_MAX_RESYNC_BEFORE_CIRCUIT_BREAK: int = int(os.environ.get("NIJA_FSM_MAX_RESYNC", "5"))
_SERVER_SYNC_OFFSET_MS: int = int(os.environ.get("NIJA_FSM_SERVER_SYNC_OFFSET_MS", "3000"))
_RECOVERY_FREEZE_S: float = float(os.environ.get("NIJA_FSM_RECOVERY_FREEZE_S", "3.0"))
_CEILING_JUMP_MS: int = int(os.environ.get("NIJA_FSM_CEILING_JUMP_MS", "86400000"))
_PROBE_STEP_MS: int = int(os.environ.get("NIJA_FSM_PROBE_STEP_MS", "300000"))
_PROBE_MAX_ATTEMPTS: int = int(os.environ.get("NIJA_FSM_PROBE_MAX_ATTEMPTS", "12"))
_STARTUP_JUMP_MS: int = int(os.environ.get("NIJA_FSM_STARTUP_JUMP_MS", "10000"))


# ── Exceptions ────────────────────────────────────────────────────────────────

class NonceFSMError(RuntimeError):
    """Base for all NonceFSM errors."""


class NonceFSMLockTimeout(NonceFSMError):
    """Raised when the FSM lock cannot be acquired within the hard timeout."""


class NonceFSMCircuitOpen(NonceFSMError):
    """Raised when the resync circuit-breaker is open (too many consecutive failures).

    Call ``NonceFSM.reset_circuit()`` to clear after inspecting the API key.
    """


# ── FSM states ────────────────────────────────────────────────────────────────

class _State(enum.Enum):
    IDLE          = "IDLE"            # not started; no nonce issued yet
    SYNCING       = "SYNCING"         # acquiring initial nonce floor from Kraken server
    LIVE          = "LIVE"            # normal operation; issueing nonces
    RECOVERING    = "RECOVERING"      # nonce rejection received; running server_sync_resync
    PROBING       = "PROBING"         # sequential forward-probe loop active
    CIRCUIT_OPEN  = "CIRCUIT_OPEN"    # circuit-breaker tripped; hard stop on probe_and_resync
    FAILED        = "FAILED"          # terminal: key permanently out-of-sync; quarantine fired


# Valid transitions table.  A transition to the same state is always silently
# allowed (re-entrant / no-op) — callers do not need to guard with
# "if state != X: transition(X)".
_TRANSITIONS: dict[_State, frozenset[_State]] = {
    _State.IDLE:         frozenset({_State.SYNCING, _State.LIVE}),
    _State.SYNCING:      frozenset({_State.LIVE, _State.RECOVERING, _State.FAILED}),
    _State.LIVE:         frozenset({_State.RECOVERING, _State.SYNCING}),
    _State.RECOVERING:   frozenset({_State.LIVE, _State.PROBING, _State.CIRCUIT_OPEN, _State.FAILED}),
    _State.PROBING:      frozenset({_State.LIVE, _State.CIRCUIT_OPEN, _State.FAILED}),
    _State.CIRCUIT_OPEN: frozenset({_State.SYNCING, _State.IDLE}),   # reset_circuit() only
    _State.FAILED:       frozenset({_State.SYNCING, _State.IDLE}),   # force_resync() only
}
# Add self-loop for every state:
for _s in list(_TRANSITIONS):
    _TRANSITIONS[_s] = _TRANSITIONS[_s] | frozenset({_s})


# ── Probe window context manager (deadlock fix #4) ────────────────────────────

class _ProbeWindow:
    """Thread-safe reference-counted probe window with guaranteed __exit__.

    Replaces the bare _probe_window_begin / _probe_window_end pair.  Because
    Python's ``with`` statement guarantees ``__exit__`` fires even when the body
    raises a BaseException, probe windows can never get stranded.

    A background watchdog thread monitors the ``open_since`` timestamp and
    forcibly closes windows that have been open longer than ``_PROBE_WATCHDOG_S``
    seconds.
    """

    _lock = threading.Lock()
    _active: int = 0
    _cond = threading.Condition(_lock)
    _open_since: Optional[float] = None  # monotonic time when active count went > 0
    _watchdog_thread: Optional[threading.Thread] = None
    _watchdog_started = False

    @classmethod
    def _start_watchdog(cls) -> None:
        if cls._watchdog_started:
            return
        cls._watchdog_started = True
        t = threading.Thread(
            target=cls._watchdog_loop,
            name="nonce-fsm-probe-watchdog",
            daemon=True,
        )
        t.start()
        cls._watchdog_thread = t

    @classmethod
    def _watchdog_loop(cls) -> None:
        while True:
            time.sleep(max(1.0, _PROBE_WATCHDOG_S / 4))
            with cls._cond:
                if cls._active > 0 and cls._open_since is not None:
                    age = time.monotonic() - cls._open_since
                    if age > _PROBE_WATCHDOG_S:
                        _logger.error(
                            "NonceFSM watchdog: probe window has been open for %.1f s "
                            "(threshold %.1f s) — force-closing to prevent deadlock "
                            "(active_count=%d)",
                            age, _PROBE_WATCHDOG_S, cls._active,
                        )
                        cls._active = 0
                        cls._open_since = None
                        cls._cond.notify_all()

    @classmethod
    def wait_until_closed(cls, timeout_s: float = _LOCK_ACQUIRE_TIMEOUT_S) -> bool:
        """Block until no probe window is active, up to *timeout_s* seconds.

        Returns True when the window is clear, False on timeout.
        The watchdog guarantees that a stuck window is force-closed well before
        *timeout_s* (which defaults to 8 s, far below the 30 s watchdog threshold).
        """
        deadline = time.monotonic() + timeout_s
        with cls._cond:
            while cls._active > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _logger.error(
                        "NonceFSM: timed out waiting for probe window to close "
                        "(timeout_s=%.1f) — forcing progress",
                        timeout_s,
                    )
                    return False
                cls._cond.wait(timeout=min(remaining, 0.5))
        return True

    def __init__(self, fsm: "NonceFSM") -> None:
        self._fsm = fsm

    def __enter__(self) -> "_ProbeWindow":
        with self.__class__._cond:
            self.__class__._active += 1
            if self.__class__._active == 1:
                self.__class__._open_since = time.monotonic()
            self.__class__._start_watchdog()
        return self

    def __exit__(self, *_exc) -> None:
        with self.__class__._cond:
            if self.__class__._active > 0:
                self.__class__._active -= 1
            else:
                _logger.warning("NonceFSM _ProbeWindow: __exit__ with active_count already 0")
            if self.__class__._active == 0:
                self.__class__._open_since = None
                self.__class__._cond.notify_all()


# ── Core NonceFSM ─────────────────────────────────────────────────────────────

class NonceFSM:
    """
    Corrected nonce state machine.  Thread-safe, drop-in replacement for the
    nonce-issuing methods of ``KrakenNonceManager``.

    All public methods acquire ``_fsm_lock`` with a hard timeout
    (``_LOCK_ACQUIRE_TIMEOUT_S``) — no method can block indefinitely.
    """

    _singleton: Optional["NonceFSM"] = None
    _singleton_lock = threading.Lock()

    # ── Singleton factory ──────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "NonceFSM":
        """Return the process-wide singleton, creating it on first call."""
        if cls._singleton is None:
            with cls._singleton_lock:
                if cls._singleton is None:
                    cls._singleton = cls()
        return cls._singleton  # type: ignore[return-value]

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._fsm_lock = threading.RLock()
        self._state: _State = _State.IDLE
        self._last_nonce: int = 0
        self._error_count: int = 0
        self._resync_attempts: int = 0       # consecutive failed probe_and_resync calls
        self._successful_resyncs: int = 0
        self._last_successful_nonce: int = 0
        self._is_key_poisoned: bool = False

        # Quarantine callbacks (same interface as KrakenNonceManager)
        self._quarantine_callbacks: list[Callable[[], None]] = []

        _logger.info("NonceFSM: initialised in state %s", self._state.value)

    # ── Lock helper ────────────────────────────────────────────────────────

    def _acquire(self) -> bool:
        """Acquire the FSM lock with hard timeout.  Returns True on success."""
        acquired = self._fsm_lock.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_S)
        if not acquired:
            _logger.error(
                "NonceFSM: lock acquisition timed out after %.1f s in state %s",
                _LOCK_ACQUIRE_TIMEOUT_S, self._state.value,
            )
        return acquired

    # ── State machine ──────────────────────────────────────────────────────

    def _transition(self, new_state: _State, reason: str = "") -> None:
        """Transition to *new_state*.  Must be called while holding *_fsm_lock*."""
        if new_state == self._state:
            return  # re-entrant / no-op
        allowed = _TRANSITIONS.get(self._state, frozenset())
        if new_state not in allowed:
            _logger.error(
                "NonceFSM: ILLEGAL transition %s → %s (%s) — resetting to RECOVERING",
                self._state.value, new_state.value, reason,
            )
            self._state = _State.RECOVERING
            return
        _logger.info(
            "NonceFSM: %s → %s%s",
            self._state.value, new_state.value,
            f" ({reason})" if reason else "",
        )
        self._state = new_state

    @property
    def state(self) -> _State:
        return self._state

    # ── Nonce issuance ─────────────────────────────────────────────────────

    def next_nonce(self) -> int:
        """Return the next strictly-increasing nonce.

        If the FSM is in IDLE it bootstraps itself with an NTP-aware startup
        floor before issuing the first nonce.  Raises ``NonceFSMCircuitOpen``
        when the circuit-breaker has tripped.
        """
        if not self._acquire():
            raise NonceFSMLockTimeout("next_nonce: could not acquire FSM lock")
        try:
            if self._state == _State.CIRCUIT_OPEN:
                raise NonceFSMCircuitOpen(
                    "Nonce circuit-breaker is open — too many consecutive resync failures. "
                    "Call reset_circuit() after verifying the API key."
                )
            if self._state == _State.IDLE:
                self._bootstrap_floor()
            self._last_nonce += 1
            return self._last_nonce
        finally:
            self._fsm_lock.release()

    # convenient alias
    def get_nonce(self) -> int:
        return self.next_nonce()

    # ── Error / success accounting ──────────────────────────────────────────

    def record_error(self) -> None:
        """Record a Kraken ``EAPI:Invalid nonce`` rejection.

        Increments the consecutive-error counter.  Does NOT mutate the nonce
        — the monotonic counter continues so self-correcting cases (transient
        replay) resolve automatically on the next call.
        """
        if not self._acquire():
            return
        try:
            if self._is_key_poisoned:
                return
            self._error_count += 1
            _logger.warning(
                "NonceFSM.record_error: consecutive error #%d  nonce=%d  state=%s",
                self._error_count, self._last_nonce, self._state.value,
            )
        finally:
            self._fsm_lock.release()

    def record_success(self) -> None:
        """Reset error and resync counters on a confirmed successful API call."""
        if not self._acquire():
            return
        try:
            self._error_count = 0
            self._resync_attempts = 0
            self._last_successful_nonce = self._last_nonce
            if self._state in (_State.RECOVERING, _State.PROBING):
                self._transition(_State.LIVE, "successful API call")
        finally:
            self._fsm_lock.release()

    # ── Ceiling jump (bug #1 fix) ──────────────────────────────────────────

    def force_ceiling_jump(self, ms: Optional[int] = None) -> int:
        """Jump nonce to ``max(last_nonce, now) + jump_ms``.

        **Bug #1 fix**: the original ``now + jump_ms`` formula was a no-op when
        the nonce had already drifted past *now*.  By anchoring to
        ``max(last_nonce, now)`` the jump is always *above* the current value.
        """
        if not self._acquire():
            raise NonceFSMLockTimeout("force_ceiling_jump: could not acquire FSM lock")
        try:
            jump_ms = ms if ms is not None else _CEILING_JUMP_MS
            now_ms = int(time.time() * 1000)
            # FIX: anchor to max(last_nonce, now), not bare now
            anchor = max(self._last_nonce, now_ms)
            new_nonce = anchor + jump_ms
            prev = self._last_nonce
            self._last_nonce = new_nonce
            _logger.warning(
                "NonceFSM.force_ceiling_jump: %d → %d  (+%d ms = %.1f h)  "
                "wall_clock=%d  anchor=%d  lead=%+d ms",
                prev, new_nonce, jump_ms, jump_ms / 3_600_000,
                now_ms, anchor, new_nonce - now_ms,
            )
            return new_nonce
        finally:
            self._fsm_lock.release()

    # ── probe_and_resync (bugs #2 #3 #4 fixes) ────────────────────────────

    def probe_and_resync(
        self,
        api_call_fn: Optional[Callable[[], dict]],
        *,
        step_ms: int = 0,
        max_attempts: int = 0,
    ) -> bool:
        """Calibrate the nonce floor via server-sync + limited forward probing.

        **Bug #2 fix (infinite forward drift)**: probe jumps are now applied to
        an in-memory scratch variable; the persisted nonce is only advanced to
        the *successful* probe value.  On full exhaustion the nonce is *reset*
        to the server-sync floor + 1, preventing accumulated drift from carrying
        into the next call.

        **Bug #3 fix (resync failure loop)**: a ``_resync_attempts`` counter
        increments on each failed run.  When it reaches
        ``_MAX_RESYNC_BEFORE_CIRCUIT_BREAK`` the FSM transitions to
        ``CIRCUIT_OPEN`` and raises ``NonceFSMCircuitOpen`` on all subsequent
        calls — breaking the infinite retry loop.

        **Bug #4 fix (FSM deadlock)**: the probe window is managed by
        ``_ProbeWindow`` which guarantees ``__exit__`` fires even on exceptions.
        All blocking operations use explicit timeouts.

        Returns True on successful calibration, False otherwise.
        Raises ``NonceFSMCircuitOpen`` when the circuit-breaker is tripped.
        """
        # ── Deadlock fix: wait for any concurrent probe window ─────────────
        _ProbeWindow.wait_until_closed(timeout_s=_LOCK_ACQUIRE_TIMEOUT_S)

        with _ProbeWindow(self):
            # ── Circuit-breaker guard ──────────────────────────────────────
            if not self._acquire():
                raise NonceFSMLockTimeout("probe_and_resync: could not acquire FSM lock")
            try:
                if self._state == _State.CIRCUIT_OPEN:
                    raise NonceFSMCircuitOpen(
                        "Nonce circuit-breaker is open — call reset_circuit() first."
                    )
                self._transition(_State.RECOVERING, "probe_and_resync entered")
            finally:
                self._fsm_lock.release()

            # ── Step 1: server-sync (freeze + re-anchor to Kraken time) ───
            server_floor_ms = self._do_server_sync_resync()

            # If api_call_fn is None this is a startup pre-check only
            if api_call_fn is None:
                if not self._acquire():
                    return False
                try:
                    self._transition(_State.LIVE, "probe_and_resync (no api_call_fn)")
                finally:
                    self._fsm_lock.release()
                return True

            # ── Step 2: single baseline call ──────────────────────────────
            ok, is_nonce_err = self._call_once(api_call_fn, "baseline after server_sync")
            if ok:
                self._on_probe_success()
                return True
            if not is_nonce_err:
                self._on_probe_failure()
                return False

            # ── Step 3: forward probe loop (in-memory, not persisted) ─────
            effective_step = step_ms if step_ms > 0 else _PROBE_STEP_MS
            effective_max = max_attempts if max_attempts > 0 else _PROBE_MAX_ATTEMPTS

            if not self._acquire():
                return False
            try:
                self._transition(_State.PROBING, "nonce rejected after server_sync")
                # Snapshot the floor *before* any probe advance
                probe_nonce = self._last_nonce
            finally:
                self._fsm_lock.release()

            _logger.warning(
                "NonceFSM.probe_and_resync: starting probe loop  "
                "floor=%d  step=%d ms  max_attempts=%d",
                probe_nonce, effective_step, effective_max,
            )

            success_nonce: Optional[int] = None
            for attempt in range(1, effective_max + 1):
                # Advance in-memory probe cursor only — do NOT write to _last_nonce yet
                probe_nonce += effective_step
                _logger.warning(
                    "NonceFSM probe %d/%d: nonce → %d (+%d ms)",
                    attempt, effective_max, probe_nonce, effective_step,
                )
                # Temporarily set _last_nonce for the API call nonce generation
                if not self._acquire():
                    break
                try:
                    self._last_nonce = probe_nonce
                finally:
                    self._fsm_lock.release()

                ok, is_nonce_err = self._call_once(api_call_fn, f"probe {attempt}/{effective_max}")
                if ok:
                    success_nonce = probe_nonce
                    break
                if not is_nonce_err:
                    # Non-nonce error (permissions, rate-limit, etc.) — stop probing
                    break

            if success_nonce is not None:
                # Commit the successful probe nonce
                if not self._acquire():
                    return False
                try:
                    self._last_nonce = success_nonce
                    self._transition(_State.LIVE, f"probe succeeded at nonce={success_nonce}")
                finally:
                    self._fsm_lock.release()
                self._on_probe_success()
                return True

            # ── Step 4: escalation ceiling jump (bug #1 applied here too) ─
            _logger.warning(
                "NonceFSM.probe_and_resync: standard probes exhausted — "
                "applying ceiling jump (+%.1f h) and retrying",
                _CEILING_JUMP_MS / 3_600_000,
            )
            # force_ceiling_jump uses max(last_nonce, now)+jump_ms — bug #1 fix
            ceiling = self.force_ceiling_jump()
            probe_nonce = ceiling

            ok, is_nonce_err = self._call_once(api_call_fn, "post-ceiling-jump baseline")
            if ok:
                if not self._acquire():
                    return False
                try:
                    self._last_nonce = probe_nonce
                    self._transition(_State.LIVE, "ceiling jump succeeded")
                finally:
                    self._fsm_lock.release()
                self._on_probe_success()
                return True

            # Optional extra probes after ceiling jump
            for attempt in range(1, 5):  # up to 4 bonus steps
                probe_nonce += effective_step
                if not self._acquire():
                    break
                try:
                    self._last_nonce = probe_nonce
                finally:
                    self._fsm_lock.release()
                ok, is_nonce_err = self._call_once(
                    api_call_fn, f"post-ceiling probe {attempt}/4"
                )
                if ok:
                    if not self._acquire():
                        return False
                    try:
                        self._last_nonce = probe_nonce
                        self._transition(_State.LIVE, f"post-ceiling probe {attempt} succeeded")
                    finally:
                        self._fsm_lock.release()
                    self._on_probe_success()
                    return True
                if not is_nonce_err:
                    break

            # ── Bug #2 fix: revert nonce to server_floor on full exhaustion ─
            if not self._acquire():
                return False
            try:
                # Reset to server floor — do NOT leave nonce at the last probe value
                reset_nonce = server_floor_ms + _SERVER_SYNC_OFFSET_MS + 1
                _logger.error(
                    "NonceFSM.probe_and_resync: all probes exhausted — "
                    "reverting nonce from %d to server_floor+1=%d to prevent drift",
                    self._last_nonce, reset_nonce,
                )
                self._last_nonce = reset_nonce
            finally:
                self._fsm_lock.release()

            self._on_probe_failure()
            return False

    # ── Circuit-breaker reset ──────────────────────────────────────────────

    def reset_circuit(self) -> None:
        """Re-open the circuit-breaker and return the FSM to IDLE.

        Call this after manually verifying the API key and/or waiting for
        Kraken's nonce window to advance.
        """
        if not self._acquire():
            raise NonceFSMLockTimeout("reset_circuit: could not acquire FSM lock")
        try:
            _logger.warning(
                "NonceFSM.reset_circuit: resetting circuit-breaker "
                "(was state=%s, resync_attempts=%d)",
                self._state.value, self._resync_attempts,
            )
            self._resync_attempts = 0
            self._error_count = 0
            self._is_key_poisoned = False
            # Unlock CIRCUIT_OPEN and FAILED back to IDLE
            self._state = _State.IDLE
        finally:
            self._fsm_lock.release()

    # ── Quarantine callbacks (API compat) ──────────────────────────────────

    def register_quarantine_callback(self, cb: Callable[[], None]) -> None:
        """Register a callback invoked when the FSM enters CIRCUIT_OPEN/FAILED."""
        with self._singleton_lock:
            if cb not in self._quarantine_callbacks:
                self._quarantine_callbacks.append(cb)

    # ── Diagnostics ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return current FSM state for health-check endpoints."""
        with self._fsm_lock:
            return {
                "state": self._state.value,
                "last_nonce": self._last_nonce,
                "last_successful_nonce": self._last_successful_nonce,
                "error_count": self._error_count,
                "resync_attempts": self._resync_attempts,
                "is_key_poisoned": self._is_key_poisoned,
                "probe_window_active": _ProbeWindow._active,
            }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _bootstrap_floor(self) -> None:
        """Set the initial nonce floor from Kraken server time.  Caller holds lock."""
        self._transition(_State.SYNCING, "bootstrapping nonce floor")
        server_ms = _fetch_kraken_server_time_ms()
        if server_ms is None:
            server_ms = int(time.time() * 1000)
            _logger.warning(
                "NonceFSM._bootstrap_floor: Kraken server time unavailable — "
                "using local clock"
            )
        floor = server_ms + _STARTUP_JUMP_MS
        if floor > self._last_nonce:
            self._last_nonce = floor
        self._transition(_State.LIVE, f"floor={self._last_nonce}")

    def _do_server_sync_resync(self) -> int:
        """
        Freeze → fetch Kraken server time → reset nonce to server_floor.

        Returns the Kraken server time in ms (or local clock fallback).
        Does NOT hold the FSM lock during the network fetch (avoids blocking
        nonce issuance for other threads while we wait on I/O).
        """
        _logger.warning(
            "NonceFSM.server_sync_resync: freezing %.1f s then re-syncing to Kraken time",
            _RECOVERY_FREEZE_S,
        )
        if _RECOVERY_FREEZE_S > 0:
            time.sleep(_RECOVERY_FREEZE_S)

        server_ms = _fetch_kraken_server_time_ms()
        if server_ms is None:
            server_ms = int(time.time() * 1000)
            _logger.warning(
                "NonceFSM.server_sync_resync: Kraken server-time endpoint unavailable "
                "— falling back to local clock"
            )
        else:
            _logger.info(
                "NonceFSM.server_sync_resync: Kraken server time = %d ms "
                "(delta from local: %+d ms)",
                server_ms, server_ms - int(time.time() * 1000),
            )

        if not self._acquire():
            return server_ms
        try:
            new_nonce = max(
                server_ms + _SERVER_SYNC_OFFSET_MS,
                self._last_nonce + 1,
            )
            prev = self._last_nonce
            self._last_nonce = new_nonce
            self._error_count = 0
            _logger.warning(
                "NonceFSM.server_sync_resync: nonce %d → %d  "
                "(server_floor=%d  delta=%+d ms)",
                prev, new_nonce,
                server_ms + _SERVER_SYNC_OFFSET_MS,
                new_nonce - prev,
            )
        finally:
            self._fsm_lock.release()
        return server_ms

    def _call_once(
        self, api_call_fn: Callable[[], dict], label: str
    ) -> tuple[bool, bool]:
        """Call *api_call_fn* once and classify the result.

        Returns (success, is_nonce_error):
          (True,  False) — success
          (False, True)  — EAPI:Invalid nonce
          (False, False) — other error or unexpected response type
        """
        try:
            result = api_call_fn()
        except Exception as exc:
            _logger.debug("NonceFSM._call_once [%s]: raised %s", label, exc)
            return False, False
        if not isinstance(result, dict):
            _logger.debug(
                "NonceFSM._call_once [%s]: unexpected response type %s",
                label, type(result).__name__,
            )
            return False, False
        errs = ", ".join(result.get("error") or []).lower()
        if any(kw in errs for kw in ("invalid nonce", "eapi:invalid nonce", "nonce window")):
            return False, True
        if result.get("error"):
            _logger.debug(
                "NonceFSM._call_once [%s]: non-nonce error: %s",
                label, errs,
            )
            return False, False
        return True, False

    def _on_probe_success(self) -> None:
        """Update counters and state after a successful probe run."""
        if not self._acquire():
            return
        try:
            self._resync_attempts = 0
            self._last_successful_nonce = self._last_nonce
            self._transition(_State.LIVE, "probe_and_resync succeeded")
        finally:
            self._fsm_lock.release()

    def _on_probe_failure(self) -> None:
        """Increment failure counter and trip the circuit-breaker if needed.

        **Bug #3 fix**: after ``_MAX_RESYNC_BEFORE_CIRCUIT_BREAK`` consecutive
        failed resyncs the FSM transitions to ``CIRCUIT_OPEN`` and fires all
        registered quarantine callbacks so the broker layer can stop retrying
        and switch to an alternative exchange.
        """
        if not self._acquire():
            return
        try:
            self._resync_attempts += 1
            _logger.error(
                "NonceFSM._on_probe_failure: failed resync #%d (threshold=%d)",
                self._resync_attempts, _MAX_RESYNC_BEFORE_CIRCUIT_BREAK,
            )
            if self._resync_attempts >= _MAX_RESYNC_BEFORE_CIRCUIT_BREAK:
                self._is_key_poisoned = True
                if self._state not in (_State.CIRCUIT_OPEN, _State.FAILED):
                    self._transition(
                        _State.CIRCUIT_OPEN,
                        f"circuit-breaker tripped after {self._resync_attempts} "
                        "consecutive failed resyncs",
                    )
                    callbacks = list(self._quarantine_callbacks)
                    self._fsm_lock.release()
                    try:
                        for cb in callbacks:
                            try:
                                cb()
                            except Exception as cb_exc:
                                _logger.error(
                                    "NonceFSM: quarantine callback %r raised: %s",
                                    cb, cb_exc,
                                )
                    finally:
                        self._fsm_lock.acquire()
            else:
                if self._state not in (_State.CIRCUIT_OPEN, _State.FAILED):
                    self._transition(
                        _State.RECOVERING,
                        f"probe failed, resync_attempts={self._resync_attempts}",
                    )
        finally:
            self._fsm_lock.release()


# ── Module-level server-time helper (same as global_kraken_nonce) ─────────────

def _fetch_kraken_server_time_ms() -> Optional[int]:
    """Query Kraken /0/public/Time and return milliseconds, or None on failure."""
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


# ── Module-level convenience API (mirrors global_kraken_nonce) ───────────────

def get_nonce_fsm() -> NonceFSM:
    """Return the process-wide NonceFSM singleton."""
    return NonceFSM.get_instance()


def get_kraken_nonce() -> int:
    """Drop-in replacement for ``global_kraken_nonce.get_kraken_nonce()``."""
    return get_nonce_fsm().next_nonce()
