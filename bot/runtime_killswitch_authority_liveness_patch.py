"""Preserve heartbeat kill-switch causality and recover only retired heartbeat stops.

This runtime patch is deliberately non-authoritative: it never creates a kill
switch stop, never grants execution authority, never forces LIVE_ACTIVE, and
never releases the canonical writer lease.

It closes two production convergence defects:

* legacy heartbeat-owned emergency stops could be persisted with the default
  ``MANUAL`` source, preventing the v132 restart recovery from recognizing the
  retired pre-v129 ``AUTHORITY_HEARTBEAT_EXPIRED/core_thread_dead`` race; and
* v130 required SEAK to be clear before clearing that persisted heartbeat stop,
  while the heartbeat-owned SEAK recovery required the kill switch to be clear
  first. This circular dependency could leave an otherwise healthy runtime in
  EMERGENCY_STOP indefinitely.

Recovery remains narrow and fail closed. The latest kill-switch record must be
restart persistence, the causal reason must be the exact retired heartbeat/core
failure signature, the current writer lease/core/readiness/bootstrap proofs must
all be healthy, and any SEAK halt must itself be heartbeat-owned. Recovery
returns the trading FSM to OFF and resumes only that heartbeat-owned SEAK halt;
normal activation gates must reconverge before any dispatch can occur.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_killswitch_authority_liveness")
MARKER = "20260817-runtime-killswitch-authority-liveness-v140"
_FLAG = "NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY"
_LOCK = threading.RLock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_KILL_PATCH_ATTR = "_nija_heartbeat_killswitch_provenance_v140"
_HEARTBEAT_PATCH_ATTR = "_nija_heartbeat_owned_stop_provenance_v140"
_WRITER_PATCH_ATTR = "_nija_canonical_writer_release_diagnostic_v140"
_V132_PATCH_ATTR = "_nija_heartbeat_persisted_stop_recovery_v140"
_OWNED_STOP_ENV = "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP"
_OWNED_REASON_ENV = "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP_REASON"
_LAST_WRITER_DIAGNOSTIC: dict[str, float] = {}
_ANNOUNCED = False


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _truthy_env(name: str) -> bool:
    return _truthy(os.environ.get(name, ""))


def _heartbeat_failure_reason(reason: object) -> bool:
    """Match only the retired authority-heartbeat/core-death stop signature."""
    text = str(reason or "").strip().upper()
    if not text:
        return False
    heartbeat = "AUTHORITY_HEARTBEAT_EXPIRED" in text or "AUTHORITY HEARTBEAT EXPIRED" in text
    dead_core = "CORE_THREAD_DEAD" in text or "NIJA_CORE_THREAD_ALIVE" in text
    return heartbeat and dead_core


def _explicit_manual_reason(reason: object) -> bool:
    text = str(reason or "").strip().lower()
    return any(token in text for token in ("operator", "manual", "ui stop", "cli stop"))


def _normalized_activation_source(reason: object, source: object) -> str:
    """Preserve AUTOMATIC provenance for a runtime-proven heartbeat-owned stop.

    ``KillSwitch.activate`` defaults ``source`` to MANUAL. That remains the
    default for generic callers. Reclassification occurs only when the
    authority-heartbeat callback has already published its owned-stop marker,
    the callback's recorded reason matches the retired heartbeat/core failure,
    and the activation was not explicitly described as an operator/manual stop.
    """

    normalized = str(source or "MANUAL").strip() or "MANUAL"
    if normalized.upper() != "MANUAL":
        return normalized
    if _explicit_manual_reason(reason):
        return normalized
    if not _truthy_env(_OWNED_STOP_ENV):
        return normalized
    owned_reason = os.environ.get(_OWNED_REASON_ENV, "")
    if not (_heartbeat_failure_reason(reason) or _heartbeat_failure_reason(owned_reason)):
        return normalized
    return "AUTOMATIC"


def _causal_activation(status: dict[str, Any]) -> tuple[str, str]:
    history = list(status.get("recent_history") or [])
    if not history:
        return "", ""
    latest = history[-1] if isinstance(history[-1], dict) else {}
    latest_reason = str(latest.get("reason") or "")
    latest_source = str(latest.get("source") or "")
    if latest_source.strip().upper() == "FILE_SYSTEM" and "Kill switch file detected" in latest_reason:
        for item in reversed(history[:-1]):
            if not isinstance(item, dict) or not item.get("source"):
                continue
            reason = str(item.get("reason") or "")
            source = str(item.get("source") or "")
            if source.strip().upper() == "FILE_SYSTEM" and "Kill switch file detected" in reason:
                continue
            return reason, source
    return latest_reason, latest_source


def _eligible_persisted_heartbeat_stop(status: dict[str, Any]) -> tuple[bool, str]:
    """Accept only restart-persisted retired heartbeat stops.

    MANUAL is accepted solely as a compatibility classification when the reason
    itself is the exact retired heartbeat/core-death signature. Ordinary
    MANUAL/UI/CLI/FILE_SYSTEM and unrelated automatic risk stops are preserved.
    """

    history = list(status.get("recent_history") or [])
    if not history or not isinstance(history[-1], dict):
        return False, "history_missing"
    latest = history[-1]
    latest_reason = str(latest.get("reason") or "")
    latest_source = str(latest.get("source") or "").strip().upper()
    if latest_source != "FILE_SYSTEM" or "Kill switch file detected" not in latest_reason:
        return False, "latest_not_restart_persistence"

    reason, source = _causal_activation(status)
    source_u = str(source or "").strip().upper()
    if not _heartbeat_failure_reason(reason):
        return False, "causal_reason_not_retired_heartbeat"
    if source_u in {"UI", "CLI", "FILE_SYSTEM"}:
        return False, "causal_source_forbidden"
    if source_u == "MANUAL":
        if _explicit_manual_reason(reason):
            return False, "causal_source_forbidden"
        return True, "legacy_manual_heartbeat_provenance"
    if source_u not in {"AUTO", "AUTOMATIC", "HEARTBEAT", "AUTHORITY_HEARTBEAT"}:
        return False, "causal_source_forbidden"
    return True, "automatic_heartbeat_provenance"


def _writer_core_proof() -> tuple[bool, str]:
    if os.environ.get("NIJA_AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129_INSTALLED") != "1":
        return False, "v129_not_installed"
    if not _truthy_env("NIJA_CORE_THREAD_ALIVE"):
        return False, "core_not_alive_env"

    try:
        module = importlib.import_module("bot.entrypoint_writer_authority")
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        writer = getter() if callable(getter) else None
        if writer is None:
            return False, "writer_missing"
        if not bool(getattr(writer, "acquired", False)) or bool(getattr(writer, "lost", False)):
            return False, "writer_epoch_not_current"
        if not bool(getattr(writer, "_core_thread_registered", False)):
            return False, "core_not_registered"
        core = getattr(writer, "_core_thread", None)
        alive = getattr(core, "is_alive", None) if core is not None else None
        if not callable(alive) or not bool(alive()):
            return False, "core_thread_not_live"
        renewal = getattr(writer, "_nija_lease_renewal_health", None)
        if not callable(renewal):
            return False, "writer_renewal_health_missing"
        healthy, reason, age_s, max_age_s = renewal()
        if not bool(healthy):
            return False, f"writer_renewal_unhealthy:{reason}:age={age_s}:max={max_age_s}"
    except Exception as exc:
        return False, f"writer_probe:{type(exc).__name__}:{exc}"
    return True, "writer_core_current"


def _readiness_proof() -> tuple[bool, str]:
    try:
        table = importlib.import_module("bot.readiness_table").snapshot()
        required = (
            "broker_connected",
            "balance_hydrated",
            "capital_ready",
            "risk_ready",
            "strategy_ready",
            "nonce_ready",
            "bootstrap_ready",
            "position_sync_ready",
        )
        missing = [name for name in required if not bool(table.get(name, False))]
        if missing:
            return False, "readiness:" + ",".join(missing)
    except Exception as exc:
        return False, f"readiness_probe:{type(exc).__name__}:{exc}"

    try:
        bootstrap = importlib.import_module("bot.bootstrap_state_machine")
        getter = getattr(bootstrap, "get_bootstrap_fsm", None) or getattr(
            bootstrap, "get_bootstrap_state_machine", None
        )
        fsm = getter() if callable(getter) else None
        state = getattr(fsm, "state", None) if fsm is not None else None
        state_value = str(getattr(state, "value", state) or "").strip().upper()
        if state_value != "RUNNING_SUPERVISED":
            return False, "bootstrap:" + (state_value or "unknown")
    except Exception as exc:
        return False, f"bootstrap_probe:{type(exc).__name__}:{exc}"
    return True, "readiness_current"


def _seak_status() -> tuple[Any, bool, str]:
    try:
        module = importlib.import_module("bot.single_execution_authority_kernel")
        getter = getattr(module, "get_seak", None) or getattr(
            module, "get_single_execution_authority_kernel", None
        )
        seak = getter() if callable(getter) else None
        if seak is None:
            return None, False, ""
        halted = bool(getattr(seak, "is_halted", False))
        reason = str(getattr(seak, "halt_reason", "") or getattr(seak, "_halt_reason", "") or "")
        if not reason:
            snapshot = getattr(seak, "snapshot", None)
            if callable(snapshot):
                try:
                    payload = snapshot() or {}
                    if isinstance(payload, dict):
                        reason = str(payload.get("halt_reason") or "")
                except Exception:
                    pass
        return seak, halted, reason
    except Exception as exc:
        return None, True, f"seak_probe:{type(exc).__name__}:{exc}"


def _runtime_recovery_proof() -> tuple[bool, str, Any, bool]:
    writer_ok, writer_detail = _writer_core_proof()
    if not writer_ok:
        return False, writer_detail, None, False
    readiness_ok, readiness_detail = _readiness_proof()
    if not readiness_ok:
        return False, readiness_detail, None, False

    seak, halted, seak_reason = _seak_status()
    if halted and not _heartbeat_failure_reason(seak_reason):
        return False, "seak_halt_not_heartbeat_owned:" + (seak_reason or "unknown"), seak, True
    return True, "ok", seak, halted


def _fsm_state_value() -> str:
    try:
        module = importlib.import_module("bot.trading_state_machine")
        getter = getattr(module, "get_state_machine", None)
        sm = getter() if callable(getter) else None
        state = sm.get_current_state() if sm is not None else None
        return str(getattr(state, "value", state) or "UNAVAILABLE").strip().upper()
    except Exception:
        return "UNAVAILABLE"


def _attempt_persisted_heartbeat_stop_recovery() -> bool:
    """Recover a restart-persisted retired heartbeat stop to fail-closed OFF."""
    try:
        kill_module = importlib.import_module("bot.kill_switch")
        getter = getattr(kill_module, "get_kill_switch", None)
        kill_switch = getter() if callable(getter) else None
        if kill_switch is None:
            return False
        status = kill_switch.get_status()
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_PERSISTED_STOP_RECOVERY_DEFERRED marker=%s detail=kill_switch_probe:%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    if not bool(status.get("is_active")):
        return False
    eligible, provenance = _eligible_persisted_heartbeat_stop(status)
    if not eligible:
        return False

    healthy, detail, seak, seak_halted = _runtime_recovery_proof()
    if not healthy:
        LOGGER.warning(
            "HEARTBEAT_PERSISTED_STOP_RECOVERY_DEFERRED marker=%s provenance=%s detail=%s "
            "trading_fail_closed=true",
            MARKER,
            provenance,
            detail,
        )
        return False

    causal_reason, causal_source = _causal_activation(status)
    try:
        kill_switch.deactivate(
            "verified recovery from retired authority-heartbeat/core-death restart persistence"
        )
        if bool(kill_switch.is_active()):
            LOGGER.critical(
                "HEARTBEAT_PERSISTED_STOP_RECOVERY_REFUSED marker=%s still_active=true trading_fail_closed=true",
                MARKER,
            )
            return False
    except Exception as exc:
        LOGGER.critical(
            "HEARTBEAT_PERSISTED_STOP_RECOVERY_FAILED marker=%s stage=kill_switch_deactivate "
            "err=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    # KillSwitch.deactivate() is expected to return the trading FSM to OFF.
    # Verify that invariant before releasing the independent SEAK halt.
    fsm_state = _fsm_state_value()
    if fsm_state != "OFF":
        LOGGER.critical(
            "HEARTBEAT_PERSISTED_STOP_RECOVERY_INCOMPLETE marker=%s "
            "reason=fsm_not_off_after_kill_switch_clear state=%s "
            "seak_remains_fail_closed=true force_live=false",
            MARKER,
            fsm_state,
        )
        return False

    # Resume only the SEAK halt already proven to be owned by this same retired
    # heartbeat stop. Any failure here leaves SEAK halted and execution closed.
    if seak_halted and seak is not None:
        resume = getattr(seak, "resume", None)
        if not callable(resume):
            LOGGER.critical(
                "HEARTBEAT_PERSISTED_STOP_RECOVERY_INCOMPLETE marker=%s reason=seak_resume_missing "
                "trading_fail_closed=true",
                MARKER,
            )
            return False
        try:
            resume(caller="runtime_killswitch_authority_liveness_v140")
        except Exception as exc:
            LOGGER.critical(
                "HEARTBEAT_PERSISTED_STOP_RECOVERY_INCOMPLETE marker=%s stage=seak_resume "
                "err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

    os.environ.pop(_OWNED_STOP_ENV, None)
    os.environ.pop(_OWNED_REASON_ENV, None)
    LOGGER.critical(
        "HEARTBEAT_PERSISTED_STOP_RECOVERED marker=%s provenance=%s causal_source=%s "
        "causal_reason=%s writer_core_current=true readiness_current=true "
        "seak_resumed=%s fsm_target=OFF force_live=false execution_authority_unchanged=true",
        MARKER,
        provenance,
        causal_source or "unknown",
        causal_reason or "unknown",
        str(bool(seak_halted)).lower(),
    )
    return True


def _patch_kill_switch() -> bool:
    module = importlib.import_module("bot.kill_switch")
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "activate", None)
    if not callable(current):
        return False
    if getattr(current, _KILL_PATCH_ATTR, False):
        return True

    @wraps(current)
    def activate_with_heartbeat_provenance(
        self: Any,
        reason: str,
        source: str = "MANUAL",
    ) -> Any:
        normalized = _normalized_activation_source(reason, source)
        if normalized != (str(source or "MANUAL").strip() or "MANUAL"):
            LOGGER.critical(
                "HEARTBEAT_KILL_SWITCH_SOURCE_NORMALIZED marker=%s "
                "source_before=%s source_after=%s reason=%s",
                MARKER,
                source or "MANUAL",
                normalized,
                reason,
            )
        return current(self, reason, normalized)

    setattr(activate_with_heartbeat_provenance, _KILL_PATCH_ATTR, True)
    cls.activate = activate_with_heartbeat_provenance
    return True


def _patch_authority_heartbeat_callback() -> bool:
    module = importlib.import_module("bot.authority_heartbeat")
    current = getattr(module, "_default_lockdown_callback", None)
    if not callable(current):
        return False
    if getattr(current, _HEARTBEAT_PATCH_ATTR, False):
        return True

    @wraps(current)
    def heartbeat_owned_lockdown(reason: str) -> Any:
        os.environ[_OWNED_STOP_ENV] = "1"
        os.environ[_OWNED_REASON_ENV] = str(reason or "unknown")
        return current(reason)

    setattr(heartbeat_owned_lockdown, _HEARTBEAT_PATCH_ATTR, True)
    module._default_lockdown_callback = heartbeat_owned_lockdown

    existing = getattr(module, "_monitor_instance", None)
    if existing is not None:
        callback = getattr(existing, "_lockdown_callback", None)
        if callback is current:
            existing._lockdown_callback = heartbeat_owned_lockdown
    return True


def _writer_diagnostic_interval_s() -> float:
    try:
        return max(
            60.0,
            float(os.environ.get("NIJA_CANONICAL_WRITER_RELEASE_DIAGNOSTIC_INTERVAL_S", "300") or 300.0),
        )
    except (TypeError, ValueError):
        return 300.0


def _patch_stalled_writer_release_guard() -> bool:
    guard = importlib.import_module("bot.stalled_writer_release_guard_v22")
    v58 = importlib.import_module("bot.final_production_activation_repair_v58_patch")
    current = getattr(guard, "_should_release", None)
    if not callable(current):
        return False
    if getattr(current, _WRITER_PATCH_ATTR, False):
        return True

    @wraps(current)
    def should_release_with_canonical_owner(
        snapshot: Any,
        elapsed_s: float,
        timeout_s: float,
    ) -> bool:
        canonical = bool(v58._canonical_fast_path())
        if not canonical:
            return bool(current(snapshot, elapsed_s, timeout_s))

        # v58 intentionally makes the canonical Render path diagnostic-only:
        # bot_main owns shutdown/re-election and this legacy guard must never
        # compare-and-delete the writer lease behind it. Preserve that safety
        # contract, but stop describing a live registered core as "startup".
        if elapsed_s >= timeout_s:
            core_live = bool(v58._canonical_core_registered())
            phase = "runtime_core_live" if core_live else "startup_handoff"
            generation = str(getattr(snapshot, "generation", "0") or "0")
            state = str(getattr(snapshot, "state", "unknown") or "unknown")
            key = f"{generation}:{phase}:{state}"
            now = time.monotonic()
            last = _LAST_WRITER_DIAGNOSTIC.get(key, 0.0)
            if now - last >= _writer_diagnostic_interval_s():
                _LAST_WRITER_DIAGNOSTIC[key] = now
                LOGGER.warning(
                    "WRITER_RELEASE_SUPPRESSED_BY_CANONICAL_OWNER marker=%s "
                    "phase=%s elapsed_s=%.1f timeout_s=%.1f state=%s generation=%s "
                    "writer_release_owner=bot_main core_live=%s destructive_release=false",
                    MARKER,
                    phase,
                    elapsed_s,
                    timeout_s,
                    state,
                    generation,
                    str(core_live).lower(),
                )
        return False

    setattr(should_release_with_canonical_owner, _WRITER_PATCH_ATTR, True)
    guard._should_release = should_release_with_canonical_owner
    return True


def _reassert_runtime_wrappers() -> bool:
    try:
        return bool(
            _patch_authority_heartbeat_callback()
            and _patch_kill_switch()
            and _patch_stalled_writer_release_guard()
        )
    except Exception as exc:
        LOGGER.warning(
            "RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_REASSERT_FAILED marker=%s err=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _patch_v132_durability() -> bool:
    v132 = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
    current = getattr(v132, "_attempt_persisted_stop_recovery", None)
    if not callable(current):
        return False
    if getattr(current, _V132_PATCH_ATTR, False):
        return True

    @wraps(current)
    def durable_recovery_v140() -> bool:
        _reassert_runtime_wrappers()
        try:
            kill_module = importlib.import_module("bot.kill_switch")
            getter = getattr(kill_module, "get_kill_switch", None)
            kill_switch = getter() if callable(getter) else None
            status = kill_switch.get_status() if kill_switch is not None else {}
            eligible, _detail = _eligible_persisted_heartbeat_stop(status)
        except Exception:
            eligible = False
        if eligible:
            return _attempt_persisted_heartbeat_stop_recovery()
        return bool(current())

    setattr(durable_recovery_v140, _V132_PATCH_ATTR, True)
    v132._attempt_persisted_stop_recovery = durable_recovery_v140
    return True


def install() -> bool:
    """Install/reassert all non-authoritative convergence wrappers."""
    global _ANNOUNCED
    with _LOCK:
        try:
            ok = bool(_reassert_runtime_wrappers() and _patch_v132_durability())
        except Exception as exc:
            os.environ.pop(_FLAG, None)
            LOGGER.critical(
                "RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_INSTALL_FAILED marker=%s "
                "err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False

        if not ok:
            os.environ.pop(_FLAG, None)
            return False

        os.environ[_FLAG] = "1"
        if not _ANNOUNCED:
            _ANNOUNCED = True
            LOGGER.critical(
                "RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_INSTALLED marker=%s "
                "legacy_manual_heartbeat_compat=true heartbeat_source_preserved=true "
                "heartbeat_seak_cycle_broken=true generic_manual_stops_preserved=true "
                "kill_switch_generic_auto_clear=false writer_release=false force_live=false "
                "execution_authority_unchanged=true",
                MARKER,
            )

        # One immediate recovery check covers a stop already present when this
        # patch is installed. If proofs are not yet healthy the v132 durability
        # worker retries every five seconds without widening eligibility.
        try:
            v132 = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
            attempt = getattr(v132, "_attempt_persisted_stop_recovery", None)
            if callable(attempt):
                attempt()
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_PERSISTED_STOP_INITIAL_CHECK_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_heartbeat_failure_reason",
    "_normalized_activation_source",
    "_causal_activation",
    "_eligible_persisted_heartbeat_stop",
    "_runtime_recovery_proof",
    "_attempt_persisted_heartbeat_stop_recovery",
    "_patch_v132_durability",
    "_patch_stalled_writer_release_guard",
]
