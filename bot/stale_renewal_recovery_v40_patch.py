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
* lock missing -> transition the runtime to LOST with the canonical
  ``lock_missing_and_fencing_token_mismatch`` reason so v39 can perform bounded
  fresh-epoch re-election;
* lock owned by another writer -> transition to LOST with
  ``lock_owned_by_different_writer`` so the existing non-recoverable shutdown
  path remains authoritative;
* Redis inspection error -> remain fail closed and retry; never infer ownership.

No capital, broker, SEAK, nonce, risk, or fencing bypass is introduced.
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

_INSTALL_FLAG = "_NIJA_STALE_RENEWAL_RECOVERY_V40_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_STALE_RENEWAL_RECOVERY_V40_IMPORTLIB_HOOK"
_PATCH_ATTR = "_nija_stale_renewal_recovery_v40"
_WATCHDOG_ATTR = "_nija_stale_renewal_watchdog_v40"
_WATCHDOG_STOP_ATTR = "_nija_stale_renewal_watchdog_stop_v40"
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
    """Return (state, detail): owned, missing, other, or error."""
    client = getattr(runtime, "_client", None)
    lock_key = str(getattr(runtime, "_lock_key", "") or os.environ.get("NIJA_WRITER_LOCK_KEY", "") or "").strip()
    expected = str(getattr(runtime, "_lock_value", "") or "").strip()
    token = str(getattr(runtime, "_token", "") or os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    if client is None or not lock_key:
        return "error", "redis_client_or_lock_key_missing"
    try:
        current = _as_text(client.get(lock_key)).strip()
    except Exception as exc:
        return "error", f"redis_lock_read_error:{type(exc).__name__}:{exc}"
    if not current:
        return "missing", f"lock_missing key={lock_key}"
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


def _watchdog_loop(runtime: Any, stop_event: threading.Event) -> None:
    poll_s = _cfg_float("NIJA_STALE_RENEWAL_WATCHDOG_POLL_S", 2.0, 0.25)
    stale_confirmations = max(1, int(_cfg_float("NIJA_STALE_RENEWAL_CONFIRMATIONS", 2.0, 1.0)))
    stale_seen = 0
    last_log = 0.0

    LOGGER.critical(
        "STALE_RENEWAL_V40_WATCHDOG_STARTED marker=%s generation=%s poll_s=%.2f confirmations=%d",
        MARKER,
        getattr(runtime, "_generation", 0),
        poll_s,
        stale_confirmations,
    )

    while not stop_event.is_set():
        if bool(getattr(runtime, "lost", False)):
            return
        if not bool(getattr(runtime, "acquired", False)):
            stale_seen = 0
            stop_event.wait(poll_s)
            continue

        ok, reason, age_s, max_age_s = _runtime_health(runtime)
        if ok:
            stale_seen = 0
            stop_event.wait(poll_s)
            continue

        if reason != "renewal_success_stale":
            stale_seen = 0
            stop_event.wait(poll_s)
            continue

        stale_seen += 1
        state, detail = _inspect_lock(runtime)
        now = time.monotonic()
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
    existing = getattr(runtime, _WATCHDOG_ATTR, None)
    if existing is not None and callable(getattr(existing, "is_alive", None)) and existing.is_alive():
        return True
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_watchdog_loop,
        args=(runtime, stop_event),
        name="writer-stale-renewal-watchdog-v40",
        daemon=True,
    )
    setattr(runtime, _WATCHDOG_STOP_ATTR, stop_event)
    setattr(runtime, _WATCHDOG_ATTR, thread)
    thread.start()
    return True


def _patch_entrypoint_writer_authority(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type) or getattr(cls, _PATCH_ATTR, False):
        return False

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
        "STALE_RENEWAL_V40_ENTRYPOINT_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


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
        LOGGER.critical(
            "STALE_RENEWAL_RECOVERY_V40_INSTALLED marker=%s fail_closed=true lock_mutation=false fresh_epoch_via_v39=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()
