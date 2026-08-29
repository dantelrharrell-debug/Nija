"""NIJA stale writer-renewal recovery v40.

Production after v39 exposed one remaining writer lifecycle gap: the entrypoint
heartbeat thread can remain alive while its last successful Redis lease renewal
becomes stale. In that state the process-local writer object still reports
ACTIVE/acquired, but the Redis process writer lock can expire. Because the
runtime never transitions to LOST, v39's bounded fresh-epoch re-election callback
is never triggered.

v40 adds a fail-closed watchdog around the canonical EntrypointWriterAuthority.
It does not renew, recreate, or extend the existing writer lock. When renewal
proof becomes stale it reads the actual Redis lock:

* lock still owned by this writer -> wait; do not create a second heartbeat
  worker and do not mutate the lease;
* lock missing with a still-matching Redis fencing token -> remain fail closed
  for a short bounded recovery grace so the canonical heartbeat can exercise its
  existing safe fencing-token restoration path;
* lock missing without matching fencing proof -> transition the runtime to LOST;
* lock owned by another writer -> transition to LOST with
  ``lock_owned_by_different_writer`` so the existing non-recoverable shutdown
  path remains authoritative;
* Redis inspection error -> remain fail closed and retry; never infer ownership.

The 2026-08-29 deployment also proved a heartbeat-thread starvation path. During
pre-core startup ``EntrypointWriterAuthority._recover_core_thread_registration``
can enter import/recovery work from the Redis renewal thread. Runtime import hooks
and a long core recovery can then hold that thread for far longer than the writer
renewal freshness bound even while the exact Redis lock remains owned. The local
writer heartbeat timestamp can look fresh while the canonical Redis metadata
``heartbeat_at`` becomes stale, which correctly blocks v60 re-anchoring and then
cascades into stale capital and pending position synchronization.

v40 keeps that recovery work off the lease-renewal thread. The heartbeat path
uses only already-loaded ``bot_main`` state. Before startup is complete it returns
immediately and lets the normal bounded registration deadline remain authoritative.
After startup is complete, at most one daemon recovery worker invokes the existing
canonical recovery routine. The heartbeat never fabricates core registration,
writer renewal, readiness, capital freshness, position success, or execution
authority.

The 2026-08-29 follow-up also proved a second race: the stale-renewal watchdog
classified every missing writer lock as ``lock_missing_and_fencing_token_mismatch``
without checking the Redis fencing key. That conflicts with the canonical
heartbeat's explicit safe recovery branch, which may restore a missing lock only
when the durable fencing token still exactly matches the runtime token. v278 makes
the watchdog use the same proof boundary. While that bounded recovery grace is
open, execution authority remains revoked. If the fence differs, the renewal
thread is dead, another writer appears, or the grace expires, the runtime is
marked LOST and restarts as before.

No capital, broker, SEAK, nonce, risk, fencing, kill-switch, position, order, or
execution-readiness bypass is introduced.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.stale_renewal_recovery_v40")
MARKER = "20260807-stale-renewal-recovery-v40"
NONBLOCKING_MARKER = "20260829-writer-renewal-nonblocking-core-recovery-v277"
MISSING_LOCK_FENCE_MARKER = "20260829-stale-renewal-missing-lock-fence-v278"

_INSTALL_FLAG = "_NIJA_STALE_RENEWAL_RECOVERY_V40_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_STALE_RENEWAL_RECOVERY_V40_IMPORTLIB_HOOK"
_PATCH_ATTR = "_nija_stale_renewal_recovery_v40"
_WATCHDOG_ATTR = "_nija_stale_renewal_watchdog_v40"
_WATCHDOG_STOP_ATTR = "_nija_stale_renewal_watchdog_stop_v40"
_WATCHDOG_GENERATION_ATTR = "_nija_stale_renewal_watchdog_generation_v40"
_RECOVERY_PATCH_ATTR = "_nija_writer_renewal_nonblocking_core_recovery_v277"
_RECOVERY_WORKER_ATTR = "_nija_core_recovery_worker_v277"
_RECOVERY_LOCK_ATTR = "_nija_core_recovery_worker_lock_v277"
_PATCH_LOCK = threading.RLock()


def _cfg_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return max(minimum, default)


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _runtime_health(runtime: Any) -> tuple[bool, str, float, float]:
    health = getattr(runtime, "_nija_lease_renewal_health", None)
    if not callable(health):
        return False, "renewal_health_unavailable", float("inf"), 0.0
    try:
        ok, reason, age_s, max_age_s = health()
        return bool(ok), str(reason or ""), float(age_s), float(max_age_s)
    except Exception as exc:
        return False, f"renewal_health_error:{type(exc).__name__}:{exc}", float("inf"), 0.0


def _inspect_lock(runtime: Any) -> tuple[str, str]:
    """Return (state, detail): owned, recoverable_missing, missing, other, error.

    ``recoverable_missing`` is intentionally narrow: the writer lock itself is
    absent, but the durable Redis fencing key still exactly equals this runtime's
    token. The canonical heartbeat already uses that same proof to safely restore
    the exact lock. This watchdog never performs the restoration itself.
    """
    client = getattr(runtime, "_client", None)
    lock_key = str(getattr(runtime, "_lock_key", "") or os.environ.get("NIJA_WRITER_LOCK_KEY", "") or "").strip()
    fencing_key = str(getattr(runtime, "_fencing_key", "") or os.environ.get("NIJA_WRITER_FENCING_KEY", "") or "").strip()
    expected = str(getattr(runtime, "_lock_value", "") or "").strip()
    token = str(getattr(runtime, "_token", "") or os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    if client is None or not lock_key:
        return "error", "redis_client_or_lock_key_missing"
    try:
        current = _as_text(client.get(lock_key)).strip()
    except Exception as exc:
        return "error", f"redis_lock_read_error:{type(exc).__name__}:{exc}"
    if not current:
        if not fencing_key or not token:
            return "missing", f"lock_missing_fencing_proof_unavailable key={lock_key}"
        try:
            fence = _as_text(client.get(fencing_key)).strip()
        except Exception as exc:
            return "error", f"redis_fence_read_error:{type(exc).__name__}:{exc}"
        if fence and fence == token:
            return (
                "recoverable_missing",
                f"lock_missing_fence_matches key={lock_key} fence_key={fencing_key} token_prefix={token[:8]}",
            )
        return (
            "missing",
            f"lock_missing_fence_mismatch key={lock_key} fence_key={fencing_key} "
            f"current_fence_prefix={fence[:8]} expected_prefix={token[:8]}",
        )
    if expected and current == expected:
        return "owned", f"lock_owned_exact key={lock_key}"
    current_token = current.split(":", 1)[0]
    if token and current_token == token:
        return "owned", f"lock_owned_token key={lock_key}"
    return "other", f"lock_owned_by_other key={lock_key} current_prefix={current_token[:8]} expected_prefix={token[:8]}"


def _mark_runtime_lost(runtime: Any, reason: str) -> bool:
    marker = getattr(runtime, "_mark_lost", None)
    if not callable(marker):
        LOGGER.critical(
            "STALE_RENEWAL_V40_MARK_LOST_UNAVAILABLE marker=%s reason=%s action=fail_closed",
            MARKER,
            reason,
        )
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
        return False
    if bool(getattr(runtime, "lost", False)):
        return True
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    LOGGER.critical(
        "STALE_RENEWAL_V40_TRANSITION_LOST marker=%s generation=%s reason=%s trading_fail_closed=true",
        MARKER,
        getattr(runtime, "_generation", 0),
        reason,
    )
    marker(reason)
    return True


def _loaded_bot_main() -> Any:
    """Return already-loaded bot_main without entering mutable import hooks."""
    return sys.modules.get("bot.bot_main") or sys.modules.get("bot_main")


def _on_writer_heartbeat_thread(runtime: Any) -> bool:
    current = threading.current_thread()
    heartbeat = getattr(runtime, "_heartbeat_thread", None)
    if heartbeat is not None and current is heartbeat:
        return True
    return str(getattr(current, "name", "") or "") == "entrypoint-writer-lock-heartbeat"


def _renewal_thread_alive(runtime: Any) -> bool:
    heartbeat = getattr(runtime, "_heartbeat_thread", None)
    if heartbeat is None or not callable(getattr(heartbeat, "is_alive", None)):
        return False
    try:
        return bool(heartbeat.is_alive())
    except Exception:
        return False


def _recovery_worker_lock(runtime: Any) -> threading.Lock:
    lock = getattr(runtime, _RECOVERY_LOCK_ATTR, None)
    if lock is not None:
        return lock
    with _PATCH_LOCK:
        lock = getattr(runtime, _RECOVERY_LOCK_ATTR, None)
        if lock is None:
            lock = threading.Lock()
            setattr(runtime, _RECOVERY_LOCK_ATTR, lock)
        return lock


def _dispatch_core_recovery_worker(runtime: Any, original: Any, source: str) -> tuple[bool, str]:
    """Dispatch at most one canonical core recovery worker without blocking Redis renewal."""
    lock = _recovery_worker_lock(runtime)
    with lock:
        worker = getattr(runtime, _RECOVERY_WORKER_ATTR, None)
        if worker is not None and callable(getattr(worker, "is_alive", None)) and worker.is_alive():
            return False, "recovery_in_flight"

        next_at = float(getattr(runtime, "_core_recovery_next_attempt_monotonic", 0.0) or 0.0)
        now = time.monotonic()
        if next_at > now:
            return False, f"recovery_backoff_active wait_s={next_at - now:.2f}"

        def _worker() -> None:
            ok = False
            detail = "unknown"
            try:
                ok, detail = original(runtime, f"{source}:background_v277")
            except Exception as exc:
                detail = f"background_recovery_exception:{type(exc).__name__}:{exc}"
                LOGGER.warning(
                    "WRITER_V277_CORE_RECOVERY_WORKER_ERROR marker=%s generation=%s error=%s:%s "
                    "writer_renewal_unchanged=true trading_fail_closed=true",
                    NONBLOCKING_MARKER,
                    getattr(runtime, "_generation", 0),
                    type(exc).__name__,
                    exc,
                )
            finally:
                LOGGER.info(
                    "WRITER_V277_CORE_RECOVERY_WORKER_COMPLETE marker=%s generation=%s ok=%s detail=%s "
                    "core_registration_fabricated=false writer_renewal_fabricated=false",
                    NONBLOCKING_MARKER,
                    getattr(runtime, "_generation", 0),
                    str(bool(ok)).lower(),
                    detail,
                )
                with lock:
                    if getattr(runtime, _RECOVERY_WORKER_ATTR, None) is threading.current_thread():
                        setattr(runtime, _RECOVERY_WORKER_ATTR, None)

        worker = threading.Thread(
            target=_worker,
            name=f"writer-core-registration-recovery-v277-g{int(getattr(runtime, '_generation', 0) or 0)}",
            daemon=True,
        )
        setattr(runtime, _RECOVERY_WORKER_ATTR, worker)
        worker.start()

    LOGGER.critical(
        "WRITER_V277_CORE_RECOVERY_DISPATCHED marker=%s generation=%s source=%s "
        "heartbeat_thread_nonblocking=true single_flight=true canonical_recovery_only=true "
        "writer_renewal_unchanged=true readiness_fabricated=false",
        NONBLOCKING_MARKER,
        getattr(runtime, "_generation", 0),
        source,
    )
    return False, "recovery_dispatched"


def _patch_nonblocking_core_recovery(cls: type) -> bool:
    """Prevent core recovery/import work from blocking the exact Redis renewal thread."""
    current = getattr(cls, "_recover_core_thread_registration", None)
    if not callable(current):
        return False
    if bool(getattr(current, _RECOVERY_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def _recover_core_thread_registration_v277(self: Any, source: str):
        if not _on_writer_heartbeat_thread(self):
            return original(self, source)

        # Never import bot_main from the Redis renewal thread. The canonical
        # launcher loads it before writer acquisition; if it is not visible yet,
        # the bounded startup registration deadline remains the authority.
        bot_main = _loaded_bot_main()
        if bot_main is None:
            return False, "startup_module_not_loaded"

        shutdown = getattr(bot_main, "_shutdown_event", None)
        if shutdown is not None and callable(getattr(shutdown, "is_set", None)):
            try:
                if shutdown.is_set():
                    return False, "shutdown_requested"
            except Exception:
                return False, "shutdown_state_unavailable"

        if not bool(getattr(bot_main, "_startup_complete", False)):
            return False, "startup_not_complete"

        return _dispatch_core_recovery_worker(self, original, source)

    setattr(_recover_core_thread_registration_v277, _RECOVERY_PATCH_ATTR, True)
    setattr(_recover_core_thread_registration_v277, "__wrapped__", original)
    cls._recover_core_thread_registration = _recover_core_thread_registration_v277
    LOGGER.critical(
        "WRITER_RENEWAL_NONBLOCKING_CORE_RECOVERY_V277_PATCHED marker=%s class=%s "
        "heartbeat_imports=false background_recovery_single_flight=true "
        "registration_deadline_unchanged=true writer_ttl_unchanged=true "
        "execution_authority_unchanged=true safety_gates_bypassed=false",
        NONBLOCKING_MARKER,
        cls.__name__,
    )
    return True


def _watchdog_loop(runtime: Any, stop_event: threading.Event) -> None:
    poll_s = _cfg_float("NIJA_STALE_RENEWAL_WATCHDOG_POLL_S", 2.0, 0.25)
    stale_confirmations = max(1, int(_cfg_float("NIJA_STALE_RENEWAL_CONFIRMATIONS", 2.0, 1.0)))
    missing_recovery_grace_s = _cfg_float(
        "NIJA_STALE_RENEWAL_MISSING_LOCK_RECOVERY_GRACE_S",
        8.0,
        1.0,
    )
    stale_seen = 0
    last_log = 0.0
    recoverable_missing_since = 0.0
    watched_generation = int(getattr(runtime, "_generation", 0) or 0)

    LOGGER.critical(
        "STALE_RENEWAL_V40_WATCHDOG_STARTED marker=%s generation=%s poll_s=%.2f confirmations=%d "
        "missing_lock_recovery_grace_s=%.1f fence_check_v278=true",
        MARKER,
        getattr(runtime, "_generation", 0),
        poll_s,
        stale_confirmations,
        missing_recovery_grace_s,
    )

    while not stop_event.is_set():
        current_generation = int(getattr(runtime, "_generation", 0) or 0)
        if current_generation != watched_generation:
            LOGGER.info(
                "STALE_RENEWAL_V40_STALE_EPOCH_EXIT marker=%s watched_generation=%s current_generation=%s",
                MARKER,
                watched_generation,
                current_generation,
            )
            return
        if bool(getattr(runtime, "lost", False)):
            return
        if not bool(getattr(runtime, "acquired", False)):
            stale_seen = 0
            recoverable_missing_since = 0.0
            stop_event.wait(poll_s)
            continue

        ok, reason, age_s, max_age_s = _runtime_health(runtime)
        if int(getattr(runtime, "_generation", 0) or 0) != watched_generation:
            LOGGER.info(
                "STALE_RENEWAL_V40_STALE_EPOCH_EXIT marker=%s watched_generation=%s current_generation=%s",
                MARKER,
                watched_generation,
                getattr(runtime, "_generation", 0),
            )
            return
        if ok:
            stale_seen = 0
            recoverable_missing_since = 0.0
            stop_event.wait(poll_s)
            continue

        if reason != "renewal_success_stale":
            stale_seen = 0
            recoverable_missing_since = 0.0
            stop_event.wait(poll_s)
            continue

        stale_seen += 1
        state, detail = _inspect_lock(runtime)
        now = time.monotonic()
        if state != "recoverable_missing":
            recoverable_missing_since = 0.0
        if now - last_log >= 5.0:
            last_log = now
            LOGGER.critical(
                "STALE_RENEWAL_V40_PROBE marker=%s generation=%s age_s=%.1f max_age_s=%.1f confirmations=%d/%d lock_state=%s detail=%s",
                MARKER,
                getattr(runtime, "_generation", 0),
                age_s,
                max_age_s,
                stale_seen,
                stale_confirmations,
                state,
                detail,
            )

        if stale_seen < stale_confirmations:
            stop_event.wait(poll_s)
            continue

        if state == "missing":
            _mark_runtime_lost(runtime, "lock_missing_and_fencing_token_mismatch")
            return
        if state == "other":
            _mark_runtime_lost(runtime, "lock_owned_by_different_writer")
            return
        if state == "recoverable_missing":
            # The lock expired, but no newer writer epoch has claimed the durable
            # fence. Only the canonical heartbeat may restore it. Keep execution
            # fail closed while giving that already-existing path a short bound.
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            if not _renewal_thread_alive(runtime):
                _mark_runtime_lost(runtime, "lock_missing_matching_fence_renewal_thread_not_alive")
                return
            if recoverable_missing_since <= 0.0:
                recoverable_missing_since = now
                LOGGER.critical(
                    "STALE_RENEWAL_V278_MISSING_LOCK_RECOVERY_GRACE marker=%s generation=%s "
                    "grace_s=%.1f detail=%s action=await_canonical_heartbeat "
                    "execution_fail_closed=true lock_mutation=false",
                    MISSING_LOCK_FENCE_MARKER,
                    getattr(runtime, "_generation", 0),
                    missing_recovery_grace_s,
                    detail,
                )
            elif now - recoverable_missing_since >= missing_recovery_grace_s:
                # Re-check at the terminal edge so a just-restored lock cannot be
                # raced by the watchdog's stale sample.
                terminal_state, terminal_detail = _inspect_lock(runtime)
                if terminal_state == "owned":
                    recoverable_missing_since = 0.0
                    stale_seen = 0
                    LOGGER.critical(
                        "STALE_RENEWAL_V278_MISSING_LOCK_RECOVERED marker=%s generation=%s "
                        "detail=%s execution_authority_not_granted=true",
                        MISSING_LOCK_FENCE_MARKER,
                        getattr(runtime, "_generation", 0),
                        terminal_detail,
                    )
                elif terminal_state == "other":
                    _mark_runtime_lost(runtime, "lock_owned_by_different_writer")
                    return
                elif terminal_state == "missing":
                    _mark_runtime_lost(runtime, "lock_missing_and_fencing_token_mismatch")
                    return
                elif terminal_state == "recoverable_missing":
                    _mark_runtime_lost(runtime, "lock_missing_matching_fence_recovery_grace_expired")
                    return
                # terminal_state=error remains fail closed and will be retried.
            stop_event.wait(poll_s)
            continue
        if state == "owned":
            # The old epoch still exists. Never start a second renewal worker or
            # mutate the lock from this watchdog. Continue fail-closed observation
            # until the canonical heartbeat succeeds again or Redis ownership
            # actually changes/expires.
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
        # state=error is also fail-closed: no ownership inference is permitted.
        stop_event.wait(poll_s)


def _start_watchdog(runtime: Any) -> bool:
    generation = int(getattr(runtime, "_generation", 0) or 0)
    existing = getattr(runtime, _WATCHDOG_ATTR, None)
    if existing is not None and callable(getattr(existing, "is_alive", None)) and existing.is_alive():
        existing_generation = int(getattr(existing, _WATCHDOG_GENERATION_ATTR, 0) or 0)
        if existing_generation == generation:
            return True
        old_stop = getattr(runtime, _WATCHDOG_STOP_ATTR, None)
        if old_stop is not None and callable(getattr(old_stop, "set", None)):
            old_stop.set()
        if existing is not threading.current_thread():
            existing.join(timeout=3.0)
        if existing.is_alive():
            LOGGER.error(
                "STALE_RENEWAL_V40_OLD_EPOCH_STILL_ALIVE marker=%s "
                "old_generation=%s new_generation=%s action=fail_closed",
                MARKER,
                existing_generation,
                generation,
            )
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            return False
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_watchdog_loop,
        args=(runtime, stop_event),
        name=f"writer-stale-renewal-watchdog-v40-g{generation}",
        daemon=True,
    )
    setattr(thread, _WATCHDOG_GENERATION_ATTR, generation)
    setattr(runtime, _WATCHDOG_STOP_ATTR, stop_event)
    setattr(runtime, _WATCHDOG_ATTR, thread)
    thread.start()
    return True


def _patch_entrypoint_writer_authority(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False

    nonblocking_ready = _patch_nonblocking_core_recovery(cls)
    if getattr(cls, _PATCH_ATTR, False):
        return bool(nonblocking_ready)

    original_activate = getattr(cls, "_activate_distributed_authority", None)
    if callable(original_activate):
        @wraps(original_activate)
        def _activate_distributed_authority(self: Any, *args: Any, **kwargs: Any):
            result = original_activate(self, *args, **kwargs)
            _start_watchdog(self)
            return result
        cls._activate_distributed_authority = _activate_distributed_authority

    original_release = getattr(cls, "release", None)
    if callable(original_release):
        @wraps(original_release)
        def release(self: Any, *args: Any, **kwargs: Any):
            stop = getattr(self, _WATCHDOG_STOP_ATTR, None)
            if stop is not None and callable(getattr(stop, "set", None)):
                stop.set()
            return original_release(self, *args, **kwargs)
        cls.release = release

    # If the singleton already acquired before this class patch landed, arm its
    # watchdog immediately instead of waiting for a future re-election.
    getter = getattr(module, "get_entrypoint_writer_authority", None)
    if callable(getter):
        try:
            runtime = getter()
            if runtime is not None and bool(getattr(runtime, "acquired", False)):
                _start_watchdog(runtime)
        except Exception:
            pass

    setattr(cls, _PATCH_ATTR, True)
    LOGGER.critical(
        "STALE_RENEWAL_V40_ENTRYPOINT_PATCHED marker=%s module=%s nonblocking_core_recovery=%s "
        "missing_lock_fence_v278=true",
        MARKER,
        module.__name__,
        str(bool(nonblocking_ready)).lower(),
    )
    return bool(nonblocking_ready)


def _interesting_module(name: str) -> bool:
    return str(name or "") in {"bot.entrypoint_writer_authority", "entrypoint_writer_authority"}


def _patch_loaded() -> bool:
    changed = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType) or not _interesting_module(name):
            continue
        try:
            changed = _patch_entrypoint_writer_authority(module) or changed
        except Exception as exc:
            LOGGER.warning(
                "STALE_RENEWAL_V40_PATCH_FAILED marker=%s module=%s err=%s",
                MARKER,
                name,
                exc,
            )
    return changed


def install_import_hook() -> bool:
    with _PATCH_LOCK:
        _patch_loaded()
        if not getattr(builtins, _INSTALL_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting_module(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _INSTALL_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if _interesting_module(name):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_STALE_RENEWAL_RECOVERY_V40_INSTALLED"] = "1"
        os.environ["NIJA_WRITER_RENEWAL_NONBLOCKING_CORE_RECOVERY_V277_READY"] = "1"
        os.environ["NIJA_STALE_RENEWAL_MISSING_LOCK_FENCE_V278_READY"] = "1"
        LOGGER.critical(
            "STALE_RENEWAL_RECOVERY_V40_INSTALLED marker=%s fail_closed=true lock_mutation=false "
            "fresh_epoch_via_v39=true nonblocking_core_recovery_v277=true "
            "missing_lock_fence_v278=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()
