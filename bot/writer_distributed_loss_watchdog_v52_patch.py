"""Read-only distributed writer-loss watchdog v52.

Production can transiently retain a locally acquired EntrypointWriterAuthority
object after the Redis process-writer lock has disappeared. Earlier recovery
logic waited for a specific renewal-health reason before inspecting Redis, which
left a gap when the heartbeat thread was stopped, missing, or still considered
fresh while the distributed lock was already gone.

v52 closes that gap with a read-only ownership probe while the runtime reports
itself acquired. It never creates, extends, deletes, or steals a writer lock.
Missing ownership transitions through the existing canonical _mark_lost path so
v39/v46 can perform bounded fresh-epoch re-election. A different current owner
remains non-recoverable. Redis read errors stay fail-closed without inferring
ownership loss.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_distributed_loss_watchdog_v52")
MARKER = "20260808-writer-distributed-loss-watchdog-v52"

_LOCK = threading.RLock()
_STARTED = False
_STOP = threading.Event()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_ENTRYPOINT_NAMES = ("bot.entrypoint_writer_authority", "entrypoint_writer_authority")


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _runtime() -> Any:
    for name in _ENTRYPOINT_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if callable(getter):
            try:
                runtime = getter()
            except Exception:
                continue
            if runtime is not None:
                return runtime
    return None


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def classify_distributed_ownership(runtime: Any) -> tuple[str, str]:
    client = getattr(runtime, "_client", None)
    lock_key = str(
        getattr(runtime, "_lock_key", "")
        or os.environ.get("NIJA_WRITER_LOCK_KEY", "")
        or ""
    ).strip()
    expected = str(getattr(runtime, "_lock_value", "") or "").strip()
    token = str(
        getattr(runtime, "_token", "")
        or os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")
        or ""
    ).strip()
    if client is None:
        return "error", "redis_client_missing"
    if not lock_key:
        return "error", "lock_key_missing"
    if not expected or not token:
        return "error", "local_writer_identity_incomplete"
    try:
        current = _as_text(client.get(lock_key)).strip()
    except Exception as exc:
        return "error", f"redis_lock_read_error:{type(exc).__name__}:{exc}"
    if not current:
        return "missing", f"lock_missing key={lock_key}"
    if current == expected:
        return "owned", f"lock_owned_exact key={lock_key}"
    current_token = current.split(":", 1)[0]
    if current_token == token:
        return "owned", f"lock_owned_token key={lock_key}"
    return (
        "other",
        f"lock_owned_by_other key={lock_key} current_prefix={current_token[:8]} expected_prefix={token[:8]}",
    )


def _mark_lost(runtime: Any, reason: str) -> bool:
    marker = getattr(runtime, "_mark_lost", None)
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    if not callable(marker):
        LOGGER.critical(
            "WRITER_DISTRIBUTED_LOSS_V52_MARK_LOST_UNAVAILABLE marker=%s reason=%s fail_closed=true",
            MARKER,
            reason,
        )
        return False
    if bool(getattr(runtime, "lost", False)):
        return True
    LOGGER.critical(
        "WRITER_DISTRIBUTED_LOSS_V52_TRANSITION_LOST marker=%s generation=%s token_prefix=%s reason=%s fresh_epoch_required=true",
        MARKER,
        getattr(runtime, "_generation", 0),
        str(getattr(runtime, "_token", "") or "")[:8],
        reason,
    )
    marker(reason)
    return True


def reconcile_once(runtime: Any | None = None) -> dict[str, Any]:
    runtime = runtime or _runtime()
    result: dict[str, Any] = {
        "ok": False,
        "state": "unavailable",
        "action": "none",
        "reason": "runtime_unavailable",
    }
    if runtime is None:
        return result
    if bool(getattr(runtime, "lost", False)):
        result.update(ok=True, state="lost", reason="runtime_already_lost")
        return result
    if not bool(getattr(runtime, "acquired", False)):
        result.update(ok=True, state="standby", reason="runtime_not_acquired")
        return result
    if bool(getattr(runtime, "_local_fallback", False)):
        _mark_lost(runtime, "local_writer_fallback_forbidden")
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
        result.update(
            state="local_fallback_forbidden",
            action="mark_lost_nonrecoverable",
            reason="distributed_writer_proof_required",
        )
        return result

    state, detail = classify_distributed_ownership(runtime)
    result["state"] = state
    result["reason"] = detail
    if state == "owned":
        result["ok"] = True
        return result
    if state == "missing":
        _mark_lost(runtime, "lock_missing_and_fencing_token_mismatch")
        result["action"] = "mark_lost_recoverable"
        return result
    if state == "other":
        _mark_lost(runtime, "lock_owned_by_different_writer")
        result["action"] = "mark_lost_nonrecoverable"
        return result

    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    result["action"] = "fail_closed_retry"
    return result


def _interval() -> float:
    try:
        return max(
            0.5,
            float(os.environ.get("NIJA_WRITER_DISTRIBUTED_LOSS_V52_POLL_S", "2.0") or 2.0),
        )
    except Exception:
        return 2.0


def _watchdog() -> None:
    last_signature = ""
    while not _STOP.wait(_interval()):
        try:
            state = reconcile_once()
            signature = f"{state.get('state')}:{state.get('action')}:{state.get('reason')}"
            if signature != last_signature:
                last_signature = signature
                level = logging.INFO if state.get("ok") else logging.WARNING
                LOGGER.log(
                    level,
                    "WRITER_DISTRIBUTED_LOSS_V52_WATCHDOG marker=%s state=%s action=%s reason=%s",
                    MARKER,
                    state.get("state"),
                    state.get("action"),
                    state.get("reason"),
                )
        except Exception as exc:
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.warning(
                "WRITER_DISTRIBUTED_LOSS_V52_WATCHDOG_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


def install_import_hook() -> bool:
    global _STARTED
    with _LOCK:
        if not _STARTED:
            _STOP.clear()
            threading.Thread(
                target=_watchdog,
                name="WriterDistributedLossWatchdogV52",
                daemon=True,
            ).start()
            _STARTED = True
        os.environ["NIJA_WRITER_DISTRIBUTED_LOSS_WATCHDOG_V52_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_DISTRIBUTED_LOSS_WATCHDOG_V52_INSTALLED marker=%s read_only=true fail_closed=true lock_mutation=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "classify_distributed_ownership",
    "reconcile_once",
]
