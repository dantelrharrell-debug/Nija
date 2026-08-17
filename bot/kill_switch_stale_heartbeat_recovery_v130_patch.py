"""Recover only kill-switch state caused by the retired v128 heartbeat race.

This patch does not provide a generic kill-switch auto-clear.  It may deactivate
only when the latest persisted activation record proves the stop was caused by
the exact pre-v129 AUTHORITY_HEARTBEAT_EXPIRED/core_thread_dead startup race and
current canonical runtime proofs are healthy.  Manual/UI/CLI/file-system stops
and every unrelated automatic risk stop remain untouched and fail closed.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_stale_heartbeat_recovery_v130")
MARKER = "20260816-kill-switch-stale-heartbeat-recovery-v130"
RELEASE_ID = "20260816-runtime-convergence-v130"
_FLAG = "NIJA_KILL_SWITCH_STALE_HEARTBEAT_RECOVERY_V130_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_FORBIDDEN_SOURCES = {"MANUAL", "UI", "CLI", "FILE_SYSTEM"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _latest_activation(status: dict[str, Any]) -> tuple[str, str]:
    history = list(status.get("recent_history") or [])
    for item in reversed(history):
        if isinstance(item, dict) and item.get("source"):
            return str(item.get("reason") or ""), str(item.get("source") or "")
    return "", ""


def _is_retired_heartbeat_stop(reason: str, source: str) -> bool:
    text = str(reason or "")
    src = str(source or "").strip().upper()
    if src in _FORBIDDEN_SOURCES:
        return False
    return "AUTHORITY_HEARTBEAT_EXPIRED" in text and "core_thread_dead" in text


def _runtime_proofs_healthy() -> tuple[bool, str]:
    if os.environ.get("NIJA_AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129_INSTALLED") != "1":
        return False, "v129_not_installed"
    if not _truthy(os.environ.get("NIJA_CORE_THREAD_ALIVE")):
        return False, "core_not_alive"

    try:
        from bot.entrypoint_writer_authority import get_entrypoint_writer_authority
        writer = get_entrypoint_writer_authority()
        if writer is None or not bool(getattr(writer, "_core_thread_registered", False)):
            return False, "core_not_registered"
    except Exception as exc:
        return False, f"writer_probe:{type(exc).__name__}"

    try:
        from bot.readiness_table import snapshot
        table = snapshot()
        required = (
            "broker_connected", "balance_hydrated", "authority_ready",
            "capital_ready", "risk_ready", "strategy_ready",
            "execution_ready", "nonce_ready", "bootstrap_ready",
        )
        missing = [key for key in required if not bool(table.get(key, False))]
        if missing:
            return False, "readiness:" + ",".join(missing)
    except Exception as exc:
        return False, f"readiness_probe:{type(exc).__name__}"

    try:
        from bot.seak_nonce_causality_v128_patch import _seak_halted
        halted, reason = _seak_halted()
        if halted:
            return False, "seak_halted:" + str(reason or "unknown")
    except Exception as exc:
        return False, f"seak_probe:{type(exc).__name__}"

    try:
        from bot.bootstrap_state_machine import get_bootstrap_state_machine
        fsm = get_bootstrap_state_machine()
        state = getattr(fsm, "state", None) or getattr(fsm, "current_state", None)
        state_value = str(getattr(state, "value", state) or "")
        if state_value != "RUNNING_SUPERVISED":
            return False, "bootstrap:" + (state_value or "unknown")
    except Exception:
        # Some deployments expose bootstrap state only through readiness.  The
        # bootstrap_ready proof above remains mandatory; do not fail open on it.
        pass

    return True, "ok"


def _attempt_recovery() -> bool:
    from bot.kill_switch import get_kill_switch

    kill_switch = get_kill_switch()
    status = kill_switch.get_status()
    if not bool(status.get("is_active")):
        return False

    reason, source = _latest_activation(status)
    if not _is_retired_heartbeat_stop(reason, source):
        LOGGER.critical(
            "KILL_SWITCH_V130_PRESERVED marker=%s source=%s reason=%s auto_clear=false",
            MARKER, source or "unknown", reason or "unknown",
        )
        return False

    healthy, detail = _runtime_proofs_healthy()
    if not healthy:
        LOGGER.warning(
            "KILL_SWITCH_V130_RECOVERY_DEFERRED marker=%s detail=%s original_reason=%s trading_fail_closed=true",
            MARKER, detail, reason,
        )
        return False

    kill_switch.deactivate(
        "v130 verified recovery from retired pre-v129 authority-heartbeat startup race"
    )
    if kill_switch.is_active():
        LOGGER.critical(
            "KILL_SWITCH_V130_RECOVERY_REFUSED marker=%s still_active=true trading_fail_closed=true",
            MARKER,
        )
        return False

    LOGGER.critical(
        "KILL_SWITCH_V130_RECOVERED marker=%s original_source=%s original_reason=%s "
        "v129_verified=true readiness_verified=true seak_halted=false canonical_activation_required=true",
        MARKER, source, reason,
    )
    return True


def _worker() -> None:
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline:
        try:
            from bot.kill_switch import get_kill_switch
            status = get_kill_switch().get_status()
            if not bool(status.get("is_active")):
                return
            reason, source = _latest_activation(status)
            if not _is_retired_heartbeat_stop(reason, source):
                _attempt_recovery()
                return
            if _attempt_recovery():
                return
        except Exception as exc:
            LOGGER.warning(
                "KILL_SWITCH_V130_RECOVERY_CHECK_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        time.sleep(2.0)


def _patch_release_manifest() -> bool:
    from bot import runtime_release_manifest_patch as manifest
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["kill_switch_stale_heartbeat_recovery_v130"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        if not _patch_release_manifest():
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
        threading.Thread(
            target=_worker,
            name="KillSwitchStaleHeartbeatRecoveryV130",
            daemon=True,
        ).start()
        LOGGER.critical(
            "KILL_SWITCH_STALE_HEARTBEAT_RECOVERY_V130_INSTALLED marker=%s release=%s "
            "generic_auto_clear=false manual_stops_preserved=true risk_stops_preserved=true "
            "canonical_activation_required=true execution_authority_unchanged=true",
            MARKER, RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_is_retired_heartbeat_stop", "_latest_activation", "_runtime_proofs_healthy",
]
