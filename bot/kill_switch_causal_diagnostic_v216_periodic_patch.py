"""Durable periodic kill-switch causal diagnostics (v216).

Production log slices after v215 deployment continued to show an active preserved
kill switch but could miss v215's one-shot startup diagnostic.  v216 makes that
read-only observability durable without changing any recovery or trading state.

The worker waits for the canonical kill-switch coordinator/provenance chain,
invokes the existing v215 diagnostic, and while a kill switch remains active
re-emits the bounded causal record at a conservative interval.  It never clears
or activates a stop, never removes or rewrites EMERGENCY_STOP, never mutates
readiness, authority, nonce, capital, position sync, risk, order, or fill state,
and never forces LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time

LOGGER = logging.getLogger("nija.kill_switch_causal_diagnostic_v216")
MARKER = "20260824-kill-switch-causal-diagnostic-periodic-v216"
_FLAG = "NIJA_KILL_SWITCH_CAUSAL_DIAGNOSTIC_V216_READY"
_LOCK = threading.RLock()
_STARTED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _dependencies_ready() -> bool:
    return bool(
        _truthy("NIJA_KILL_SWITCH_COORDINATOR_SYNC_READY")
        and _truthy("NIJA_KILL_SWITCH_PERSISTENCE_PROVENANCE_V143_READY")
        and _truthy("NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_READY")
    )


def _interval_s() -> float:
    raw = str(os.environ.get("NIJA_KILL_SWITCH_CAUSAL_DIAGNOSTIC_INTERVAL_S", "30") or "30").strip()
    try:
        return min(300.0, max(15.0, float(raw)))
    except (TypeError, ValueError):
        return 30.0


def _active() -> bool:
    try:
        module = importlib.import_module("bot.kill_switch")
        getter = getattr(module, "get_kill_switch", None)
        ks = getter() if callable(getter) else None
        status = ks.get_status() if ks is not None and callable(getattr(ks, "get_status", None)) else {}
        return bool(status.get("is_active")) if isinstance(status, dict) else False
    except Exception:
        return False


def _emit(*, force: bool = False) -> bool:
    try:
        v215 = importlib.import_module("bot.kill_switch_causal_diagnostic_v215_patch")
        emit = getattr(v215, "emit", None)
        if not callable(emit):
            return False
        if force:
            # v215 deduplicates unchanged signatures process-locally.  Clearing
            # only that diagnostic cache causes another log record; it does not
            # touch KillSwitch state or recovery policy.
            lock = getattr(v215, "_LOCK", None)
            if lock is not None:
                with lock:
                    setattr(v215, "_LAST_SIGNATURE", "")
            else:
                setattr(v215, "_LAST_SIGNATURE", "")
        return emit() is not False
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_CAUSAL_V216_EMIT_FAILED marker=%s err=%s:%s "
            "state_mutated=false trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _worker() -> None:
    announced_wait = False
    while not _dependencies_ready():
        if not announced_wait:
            announced_wait = True
            LOGGER.critical(
                "KILL_SWITCH_CAUSAL_V216_WAIT marker=%s dependencies_ready=false "
                "state_mutated=false recovery_eligibility_unchanged=true",
                MARKER,
            )
        time.sleep(1.0)

    os.environ[_FLAG] = "1"
    _emit(force=True)
    LOGGER.critical(
        "KILL_SWITCH_CAUSAL_V216_READY marker=%s ready=true interval_s=%.1f "
        "active_stop_periodic_only=true bounded_read_only=true state_mutated=false "
        "marker_mutated=false recovery_eligibility_unchanged=true "
        "execution_authority_unchanged=true safety_gates_bypassed=false",
        MARKER,
        _interval_s(),
    )

    while True:
        time.sleep(_interval_s())
        if _active():
            _emit(force=True)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return True
        _STARTED = True
        threading.Thread(
            target=_worker,
            name="KillSwitchCausalDiagnosticV216",
            daemon=True,
        ).start()
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_dependencies_ready",
    "_interval_s",
]
