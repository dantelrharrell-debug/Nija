from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_nonce_authority_snapshot_repair")
_MARKER = "20260709aj"
_HOOK_FLAG = "_NIJA_EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_HOOK_20260709AJ"
_CAN_EXEC_ATTR = "_nija_nonce_authority_snapshot_repair_can_execute_20260709aj"
_ASSERT_ATTR = "_nija_nonce_authority_snapshot_repair_assert_20260709aj"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    raw = os.environ.get(name)
    if raw is None:
        raw = default
    return str(raw).strip().lower() in _TRUE


def _decision_reason(decision: Any) -> str:
    return str(getattr(decision, "reason", "") or getattr(decision, "reason_detail", "") or "")


def _is_startup_nonce_block(decision: Any) -> bool:
    if bool(getattr(decision, "allowed", False)):
        return False
    reason = _decision_reason(decision).lower()
    first_failed = str(getattr(decision, "first_failed_gate", "") or "").lower()
    return "startup_snapshot_not_ready" in reason or (first_failed == "nonce.authority" and not bool(getattr(decision, "nonce_ready", False)))


def _live_safety_ready(module: ModuleType) -> tuple[bool, str]:
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    if os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() != "LIVE_ACTIVE":
        return False, "runtime_state_not_live_active"

    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        if bool(get_kill_switch().is_active()):
            return False, "kill_switch_active"
    except Exception as exc:
        return False, f"kill_switch_probe_failed:{exc}"

    writer_assert = getattr(module, "assert_distributed_writer_authority", None)
    if not callable(writer_assert):
        return False, "writer_assert_unavailable"
    try:
        writer_assert()
    except Exception as exc:
        return False, f"writer_not_ready:{exc}"

    runtime_nonce = getattr(module, "_runtime_nonce_authority_status", None)
    if not callable(runtime_nonce):
        return False, "runtime_nonce_probe_unavailable"
    try:
        nonce_ok, nonce_detail = runtime_nonce()
    except Exception as exc:
        return False, f"runtime_nonce_exception:{exc}"
    if not bool(nonce_ok):
        return False, f"runtime_nonce_not_ready:{nonce_detail or 'blocked'}"

    return True, "live_safety_and_runtime_nonce_ready"


def _repair_startup_nonce_snapshot(module: ModuleType, source: str) -> bool:
    ok, detail = _live_safety_ready(module)
    if not ok:
        logger.warning(
            "EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_WAITING marker=%s source=%s detail=%s",
            _MARKER,
            source,
            detail,
        )
        return False

    try:
        try:
            from bot.startup_coordinator import get_startup_coordinator
        except ImportError:
            from startup_coordinator import get_startup_coordinator  # type: ignore[import]
        coordinator = get_startup_coordinator()
        before = coordinator.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        if bool(getattr(before, "nonce_ready", False)):
            logger.info(
                "EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_NOOP marker=%s source=%s reason=startup_nonce_already_ready snapshot=%s",
                _MARKER,
                source,
                getattr(before, "snapshot_version", "unknown"),
            )
            return False

        coordinator.record_nonce_status(
            ready=True,
            detail=f"runtime_nonce_authority_verified_before_dispatch:{source}:marker={_MARKER}",
        )
        coordinator.record_activation_requested(
            requested=True,
            source=f"nonce_authority_snapshot_repair:{source}:marker={_MARKER}",
        )
        after = coordinator.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        proof = coordinator.evaluate_system_readiness_proof(after)
        if not bool(getattr(proof, "passed", False)):
            logger.warning(
                "EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_PROOF_BLOCKED marker=%s source=%s first_blocking_gate=%s failed_gates=%s nonce_ready=%s runtime_authority=%s",
                _MARKER,
                source,
                getattr(proof, "first_blocking_gate", "unknown"),
                getattr(proof, "failed_gates", []),
                getattr(after, "nonce_ready", False),
                getattr(after, "runtime_authority_state", "unknown"),
            )
            return False

        try:
            coordinator.finalize_activation_commit(after)
        except Exception as exc:
            logger.warning(
                "EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_COMMIT_SKIPPED marker=%s source=%s err=%s",
                _MARKER,
                source,
                exc,
            )

        logger.critical(
            "EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIRED marker=%s source=%s before_nonce=%s after_nonce=%s snapshot=%s runtime_authority=%s lifecycle=%s",
            _MARKER,
            source,
            getattr(before, "nonce_ready", False),
            getattr(after, "nonce_ready", False),
            getattr(after, "snapshot_version", "unknown"),
            getattr(after, "runtime_authority_state", "unknown"),
            getattr(after, "lifecycle_phase", "unknown"),
        )
        print(
            f"[NIJA-PRINT] EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIRED marker={_MARKER} source={source}",
            flush=True,
        )
        return True
    except Exception as exc:
        logger.warning(
            "EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_FAILED marker=%s source=%s err=%s",
            _MARKER,
            source,
            exc,
        )
        return False


def _patch_module(module: ModuleType) -> bool:
    patched = False
    original_can_execute = getattr(module, "can_execute", None)
    if callable(original_can_execute) and not getattr(original_can_execute, _CAN_EXEC_ATTR, False):
        @wraps(original_can_execute)
        def can_execute_with_nonce_snapshot_repair(*args: Any, **kwargs: Any):
            decision = original_can_execute(*args, **kwargs)
            if _is_startup_nonce_block(decision):
                if _repair_startup_nonce_snapshot(module, "can_execute"):
                    decision = original_can_execute(*args, **kwargs)
            return decision

        setattr(can_execute_with_nonce_snapshot_repair, _CAN_EXEC_ATTR, True)
        setattr(module, "can_execute", can_execute_with_nonce_snapshot_repair)
        patched = True

    original_assert = getattr(module, "assert_execution_dispatch_permitted", None)
    if callable(original_assert) and not getattr(original_assert, _ASSERT_ATTR, False):
        @wraps(original_assert)
        def assert_dispatch_with_nonce_snapshot_repair(*args: Any, **kwargs: Any):
            try:
                return original_assert(*args, **kwargs)
            except Exception as exc:
                text = str(exc).lower()
                if "startup_snapshot_not_ready" not in text and "nonce.authority" not in text:
                    raise
                if not _repair_startup_nonce_snapshot(module, "assert_execution_dispatch_permitted"):
                    raise
                return original_assert(*args, **kwargs)

        setattr(assert_dispatch_with_nonce_snapshot_repair, _ASSERT_ATTR, True)
        setattr(module, "assert_execution_dispatch_permitted", assert_dispatch_with_nonce_snapshot_repair)
        patched = True

    if patched:
        logger.warning("EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
        print(f"[NIJA-PRINT] EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_PATCHED marker={_MARKER}", flush=True)
    return patched


def _patch_loaded() -> None:
    for name in ("bot.execution_authority_context", "execution_authority_context"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("execution_authority_context") or str(name) in {"bot.execution_authority_context", "execution_authority_context"}:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
