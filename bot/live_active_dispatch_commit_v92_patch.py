"""LIVE_ACTIVE coordinator-dispatch commit convergence repair v92.

Production evidence showed the trading FSM could already report LIVE_ACTIVE while
StartupCoordinator still had last_committed_snapshot_version == 0. In that split
state, the v60 activation worker returned ``already_live`` even though canonical
``execution_permitted`` remained false, leaving the core loop live but unable to
dispatch orders.

v92 does not force activation or weaken any gate. It only treats LIVE_ACTIVE as
complete after StartupCoordinator.finalize_activation_commit() accepts the current
canonical readiness proof. When the sole substantive blocker is a stale activation
epoch, v92 re-records the canonical activation request to align activation_epoch to
global_epoch, rebuilds the immutable readiness proof, and commits only if that
fresh proof passes. Failed capital, readiness, authority, nonce, dispatch-health,
or kill-switch gates remain fail closed.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.live_active_dispatch_commit_v92")
MARKER = "20260814-live-active-dispatch-commit-v92"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_HOOK_FLAG = "_NIJA_LIVE_ACTIVE_DISPATCH_COMMIT_V92_IMPORT_HOOK"
_TSM_ATTR = "_nija_live_active_dispatch_commit_v92"
_V60_ATTR = "_nija_live_active_dispatch_commit_v92"
_EPOCH_RECOVERABLE_GATES = frozenset({"epoch.current", "runtime_authority.authorized"})


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return bool(
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


def _state_value(sm: Any) -> str:
    try:
        state = sm.get_current_state()
    except Exception:
        state = getattr(sm, "_current_state", "UNKNOWN")
    return str(getattr(state, "value", state) or "UNKNOWN").strip().upper()


def _snapshot_details(snapshot: Any) -> dict[str, Any]:
    return {
        "commit_version": int(getattr(snapshot, "last_committed_snapshot_version", 0) or 0),
        "runtime_authority_state": str(getattr(snapshot, "runtime_authority_state", "") or ""),
        "runtime_authority_reason": str(getattr(snapshot, "runtime_authority_reason", "") or ""),
        "execution_permitted": bool(getattr(snapshot, "execution_permitted", False)),
        "activation_epoch": int(getattr(snapshot, "activation_epoch", 0) or 0),
        "global_epoch": int(getattr(snapshot, "global_epoch", 0) or 0),
        "capital_stale": bool(getattr(snapshot, "capital_stale", False)),
        "kill_switch_active": bool(getattr(snapshot, "kill_switch_active", False)),
        "authority_ready": bool(getattr(snapshot, "authority_ready", False)),
        "nonce_ready": bool(getattr(snapshot, "nonce_ready", False)),
        "dispatch_health_ready": bool(getattr(snapshot, "dispatch_health_ready", False)),
        "pending_readiness": list(getattr(snapshot, "pending_readiness", []) or []),
    }


def _proof_details(proof: Any) -> dict[str, Any]:
    return {
        "passed": bool(getattr(proof, "passed", False)),
        "first_blocking_gate": str(getattr(proof, "first_blocking_gate", "") or ""),
        "failed_gates": list(getattr(proof, "failed_gates", []) or []),
        "gate_results": dict(getattr(proof, "gate_results", {}) or {}),
    }


def _maybe_reanchor_activation_epoch(
    coordinator: Any,
    snapshot: Any,
    *,
    source: str,
) -> tuple[Any, bool, str, dict[str, Any]]:
    """Re-anchor only the canonical activation request when epoch is stale.

    This is intentionally narrow. It may run only when:
    - no dispatch commit exists,
    - the coordinator reports global_epoch_stale,
    - epoch.current is failed,
    - every failed gate is either epoch.current or the derived
      runtime_authority.authorized gate.

    The coordinator then rebuilds and re-evaluates the full readiness proof.
    No other failed gate is repaired, marked ready, or bypassed here.
    """
    details: dict[str, Any] = {"attempted": False}
    evaluator = getattr(coordinator, "evaluate_system_readiness_proof", None)
    recorder = getattr(coordinator, "record_activation_requested", None)
    if not callable(evaluator) or not callable(recorder):
        return snapshot, False, "canonical_epoch_api_unavailable", details

    try:
        proof = evaluator(snapshot)
    except Exception as exc:
        details["proof_error"] = f"{type(exc).__name__}:{exc}"
        return snapshot, False, "readiness_proof_unavailable", details

    proof_info = _proof_details(proof)
    details["before_proof"] = proof_info
    if proof_info["passed"]:
        return snapshot, False, "readiness_proof_already_passed", details

    failed = set(proof_info["failed_gates"])
    if "epoch.current" not in failed:
        return snapshot, False, "epoch_not_blocking", details
    if not failed.issubset(_EPOCH_RECOVERABLE_GATES):
        details["non_epoch_blockers"] = sorted(failed - _EPOCH_RECOVERABLE_GATES)
        return snapshot, False, "non_epoch_blockers_present", details
    if int(getattr(snapshot, "last_committed_snapshot_version", 0) or 0) > 0:
        return snapshot, False, "dispatch_commit_already_present", details
    if str(getattr(snapshot, "runtime_authority_reason", "") or "") != "global_epoch_stale":
        return snapshot, False, "epoch_failure_not_global_epoch_stale", details
    if bool(getattr(snapshot, "kill_switch_active", False)):
        return snapshot, False, "kill_switch_active", details

    details["attempted"] = True
    recorder(
        requested=True,
        source=f"{MARKER}:{source}:epoch_reanchor",
    )
    refreshed = coordinator.build_snapshot(
        trading_state="LIVE_ACTIVE",
        activation_intent=True,
    )
    refreshed_proof = evaluator(refreshed)
    details["after_snapshot"] = _snapshot_details(refreshed)
    details["after_proof"] = _proof_details(refreshed_proof)
    if not bool(getattr(refreshed_proof, "passed", False)):
        first = str(getattr(refreshed_proof, "first_blocking_gate", "unknown") or "unknown")
        return refreshed, False, f"epoch_reanchor_proof_failed:{first}", details

    LOGGER.critical(
        "LIVE_ACTIVE_ACTIVATION_EPOCH_REANCHORED marker=%s source=%s "
        "activation_epoch=%s global_epoch=%s canonical_proof_passed=true "
        "safety_gates_preserved=true",
        MARKER,
        source,
        getattr(refreshed, "activation_epoch", 0),
        getattr(refreshed, "global_epoch", 0),
    )
    return refreshed, True, "activation_epoch_reanchored", details


def _ensure_coordinator_dispatch_commit(
    sm: Any,
    *,
    source: str,
) -> tuple[bool, str, dict[str, Any]]:
    """Finalize the canonical dispatch commit for an already-LIVE_ACTIVE FSM.

    The coordinator's own readiness proof remains the authority. This helper
    never mutates trading state, readiness keys, risk thresholds, nonce state,
    dispatch-health state, or kill-switch state.
    """
    state = _state_value(sm)
    details: dict[str, Any] = {"state": state, "source": source}
    if state != "LIVE_ACTIVE":
        return False, f"state_not_live:{state}", details
    if not _live_mode():
        return False, "live_mode_disabled", details

    try:
        module = importlib.import_module("bot.startup_coordinator")
        getter = getattr(module, "get_startup_coordinator", None)
        coordinator = getter() if callable(getter) else None
        if coordinator is None:
            return False, "startup_coordinator_unavailable", details

        before = coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )
        details["before"] = _snapshot_details(before)
        if (
            int(getattr(before, "last_committed_snapshot_version", 0) or 0) > 0
            and bool(getattr(before, "execution_permitted", False))
        ):
            return True, "dispatch_commit_already_current", details

        commit_snapshot, reanchored, reanchor_reason, reanchor_details = (
            _maybe_reanchor_activation_epoch(
                coordinator,
                before,
                source=source,
            )
        )
        details["epoch_reanchor"] = {
            "reanchored": bool(reanchored),
            "reason": reanchor_reason,
            **reanchor_details,
        }

        coordinator.finalize_activation_commit(commit_snapshot)
        after = coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )
        details["after"] = _snapshot_details(after)
        committed = int(getattr(after, "last_committed_snapshot_version", 0) or 0) > 0
        permitted = bool(getattr(after, "execution_permitted", False))
        if committed and permitted:
            LOGGER.critical(
                "LIVE_ACTIVE_DISPATCH_COMMIT_REPAIRED marker=%s source=%s "
                "commit_version=%s runtime_authority=%s epoch_reanchored=%s "
                "safety_gates_preserved=true",
                MARKER,
                source,
                getattr(after, "last_committed_snapshot_version", 0),
                getattr(after, "runtime_authority_state", "unknown"),
                bool(reanchored),
            )
            return True, "dispatch_commit_repaired", details
        return False, "dispatch_commit_not_executing_after_finalize", details
    except Exception as exc:
        details["error"] = f"{type(exc).__name__}:{exc}"
        LOGGER.warning(
            "LIVE_ACTIVE_DISPATCH_COMMIT_DEFERRED marker=%s source=%s error=%s:%s "
            "trading_remains_fail_closed=true",
            MARKER,
            source,
            type(exc).__name__,
            exc,
        )
        return False, f"dispatch_commit_deferred:{type(exc).__name__}", details


def _patch_trading_state_machine(module: ModuleType | Any | None = None) -> bool:
    if module is None:
        try:
            module = importlib.import_module("bot.trading_state_machine")
        except Exception:
            return False
    cls = getattr(module, "TradingStateMachine", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "commit_activation", None)
    if not callable(current):
        return False
    if getattr(current, _TSM_ATTR, False):
        return True

    @wraps(current)
    def commit_activation_v92(self: Any, *args: Any, **kwargs: Any) -> bool:
        ok = bool(current(self, *args, **kwargs))
        if not ok or _state_value(self) != "LIVE_ACTIVE":
            return ok
        synced, reason, details = _ensure_coordinator_dispatch_commit(
            self,
            source="trading_state_machine.commit_activation",
        )
        if not synced:
            LOGGER.critical(
                "LIVE_ACTIVE_DISPATCH_COMMIT_BLOCK marker=%s source=commit_activation "
                "reason=%s details=%s local_live=true dispatch=false",
                MARKER,
                reason,
                details,
            )
        return synced

    setattr(commit_activation_v92, _TSM_ATTR, True)
    setattr(commit_activation_v92, "__wrapped__", current)
    cls.commit_activation = commit_activation_v92
    LOGGER.critical(
        "LIVE_ACTIVE_DISPATCH_COMMIT_V92_TSM_PATCHED marker=%s "
        "live_state_requires_coordinator_commit=true",
        MARKER,
    )
    return True


def _patch_v60_worker(module: ModuleType | Any | None = None) -> bool:
    if module is None:
        try:
            module = importlib.import_module("bot.final_production_activation_repair_v60_patch")
        except Exception:
            return False
    current = getattr(module, "_activation_worker", None)
    if not callable(current):
        return False
    if getattr(current, _V60_ATTR, False):
        return True

    @wraps(current)
    def activation_worker_v92(trigger: str) -> None:
        try:
            monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
            sm = monitor._state_machine()
        except Exception:
            sm = None

        if sm is None or _state_value(sm) != "LIVE_ACTIVE":
            current(trigger)
            return

        started_at = time.time()
        synced, reason, details = _ensure_coordinator_dispatch_commit(
            sm,
            source=f"v60_activation_worker:{trigger}",
        )
        result = {
            "trigger": trigger,
            "started_at": started_at,
            "finished_at": time.time(),
            "state_before": "LIVE_ACTIVE",
            "state_after": "LIVE_ACTIVE",
            "ok": bool(synced),
            "reason": (
                "already_live_dispatch_committed"
                if synced
                else f"already_live_dispatch_pending:{reason}"
            ),
            "coordinator": details,
        }
        activation_lock = getattr(module, "_ACTIVATION_LOCK", _LOCK)
        try:
            with activation_lock:
                module._ACTIVATION_LAST_RESULT = result
        except Exception:
            module._ACTIVATION_LAST_RESULT = result

        logger = getattr(module, "logger", LOGGER)
        logger.critical(
            "ACTIVATION_SINGLE_FLIGHT_RESULT marker=%s trigger=%s ok=%s reason=%s "
            "state_before=LIVE_ACTIVE state_after=LIVE_ACTIVE",
            MARKER,
            trigger,
            bool(synced),
            result["reason"],
        )

    setattr(activation_worker_v92, _V60_ATTR, True)
    setattr(activation_worker_v92, "__wrapped__", current)
    module._activation_worker = activation_worker_v92
    LOGGER.critical(
        "LIVE_ACTIVE_DISPATCH_COMMIT_V92_V60_PATCHED marker=%s "
        "already_live_requires_dispatch_commit=true",
        MARKER,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    import sys

    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_trading_state_machine(module) or changed
    for name in (
        "bot.final_production_activation_repair_v60_patch",
        "final_production_activation_repair_v60_patch",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_v60_worker(module) or changed
    return changed


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                text = str(name or "")
                if (
                    "trading_state_machine" in text
                    or "final_production_activation_repair_v60_patch" in text
                ):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)
        _INSTALLED = True
        os.environ["NIJA_LIVE_ACTIVE_DISPATCH_COMMIT_V92_INSTALLED"] = "1"
        os.environ["NIJA_LIVE_ACTIVE_DISPATCH_COMMIT_V92_READY"] = "1"
        LOGGER.critical(
            "LIVE_ACTIVE_DISPATCH_COMMIT_V92_INSTALLED marker=%s "
            "force_activation=false risk_gates_unchanged=true nonce_gates_unchanged=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_ensure_coordinator_dispatch_commit",
    "_maybe_reanchor_activation_epoch",
    "_patch_trading_state_machine",
    "_patch_v60_worker",
]
