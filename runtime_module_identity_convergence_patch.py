"""Canonicalize startup patch modules before live trading imports begin.

Historically ``sitecustomize`` executed files from ``bot/`` under private
``nija_*`` names without registering those module objects in ``sys.modules``.
Later runtime bootstraps imported the same files as ``bot.*``, executing them a
second time and creating independent monitor flags and wrapper registries.

The active monitor thread retains the original module globals even when the
module was not registered. This guard reconstructs one module object from that
thread target, binds both names to it, and prevents the canonical import from
executing the source again.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.runtime_module_identity_convergence")
_MARKER = "20260714-module-identity-v2"
_LOCK = threading.RLock()
_STARTED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LEGACY_RISK_ATTR = "_nija_pre_dispatch_exposure_headroom_wrapped_20260707a"
_V2_RISK_ATTR = "_nija_pre_dispatch_risk_sizing_v2"
_ZERO_CAP_ATTR = "_nija_zero_streak_cap_e"
_ZERO_STATE_ATTR = "_nija_zero_signal_state_repair_v1"
_REQUIRED_RISK_MARKER = "20260714-downstream-risk-v2"
_RISK_ALIAS = "nija_downstream_risk_governor_equity_repair_patch"
_RISK_CANONICAL = "bot.downstream_risk_governor_equity_repair_patch"


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _live() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _canonical_from_globals(globals_dict: dict[str, Any]) -> tuple[str, str]:
    alias = str(globals_dict.get("__name__", "") or "").strip()
    raw_path = str(globals_dict.get("__file__", "") or "").strip()
    if not alias.startswith("nija_") or not raw_path:
        return "", ""
    path = Path(raw_path)
    if path.suffix != ".py" or path.parent.name != "bot":
        return "", ""
    return alias, f"bot.{path.stem}"


def _bot_canonical_name(module: ModuleType) -> str:
    _alias, canonical = _canonical_from_globals(vars(module))
    return canonical


def _module_quality(module: ModuleType) -> tuple[int, int]:
    marker = str(getattr(module, "_MARKER", "") or "")
    score = 0
    if marker == _REQUIRED_RISK_MARKER:
        score += 1000
    elif "downstream-risk-v2" in marker:
        score += 500
    if callable(getattr(module, "install_import_hook", None)):
        score += 10
    if callable(getattr(module, "install", None)):
        score += 5
    return score, len(vars(module))


def _module_from_globals(alias: str, globals_dict: dict[str, Any]) -> ModuleType:
    module = ModuleType(alias)
    module.__dict__.update(globals_dict)
    return module


def recover_unregistered_patch_modules_from_threads() -> dict[str, str]:
    """Recover sitecustomize modules from live ``Thread._target`` globals."""
    recovered: dict[str, str] = {}
    for thread in tuple(threading.enumerate()):
        target = getattr(thread, "_target", None)
        globals_dict = getattr(target, "__globals__", None)
        if not isinstance(globals_dict, dict):
            continue
        alias, canonical = _canonical_from_globals(globals_dict)
        if not alias or not canonical:
            continue

        recovered_module = _module_from_globals(alias, globals_dict)
        existing_alias = sys.modules.get(alias)
        existing_canonical = sys.modules.get(canonical)
        candidates = [recovered_module]
        if isinstance(existing_alias, ModuleType):
            candidates.append(existing_alias)
        if isinstance(existing_canonical, ModuleType):
            candidates.append(existing_canonical)
        selected = max(candidates, key=_module_quality)
        duplicate = len({id(item) for item in candidates}) > 1

        sys.modules[alias] = selected
        sys.modules[canonical] = selected
        recovered[canonical] = (
            f"alias={alias};thread={thread.name};marker={getattr(selected, '_MARKER', 'unknown')};"
            f"duplicate={str(duplicate).lower()}"
        )
        if duplicate:
            os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] = "1"
        logger.warning(
            "UNREGISTERED_PATCH_MODULE_RECOVERED marker=%s canonical=%s alias=%s thread=%s selected_marker=%s duplicate=%s",
            _MARKER,
            canonical,
            alias,
            thread.name,
            getattr(selected, "_MARKER", "unknown"),
            str(duplicate).lower(),
        )
    return recovered


def canonicalize_loaded_patch_modules() -> tuple[bool, dict[str, str]]:
    details = recover_unregistered_patch_modules_from_threads()
    ready = not _truthy("NIJA_DUPLICATE_PATCH_MODULE_DETECTED")
    for alias, module in list(sys.modules.items()):
        if not alias.startswith("nija_") or not isinstance(module, ModuleType):
            continue
        canonical = _bot_canonical_name(module)
        if not canonical:
            continue
        existing = sys.modules.get(canonical)
        selected = module
        if isinstance(existing, ModuleType) and existing is not module:
            selected = max((existing, module), key=_module_quality)
            ready = False
            os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] = "1"
            logger.critical(
                "DUPLICATE_PATCH_MODULE_CONVERGED marker=%s canonical=%s alias=%s selected_marker=%s",
                _MARKER,
                canonical,
                alias,
                getattr(selected, "_MARKER", "unknown"),
            )
        sys.modules[canonical] = selected
        sys.modules[alias] = selected
        details[canonical] = (
            f"same_object=true;marker={getattr(selected, '_MARKER', 'unknown')}"
        )
    return ready, details


def _chain_has_attr(func: Any, attr: str) -> tuple[bool, bool, int]:
    current = func
    seen: set[int] = set()
    found = False
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return found, True, depth
        seen.add(ident)
        found = found or bool(getattr(current, attr, False))
        nxt = getattr(current, "__wrapped__", None)
        if not callable(nxt):
            return found, False, depth
        current = nxt
        depth += 1
        if depth >= 4096:
            return found, True, depth
    return found, False, depth


def _wrapper_chain_status(func: Any) -> tuple[bool, bool, bool, int]:
    v2, cycle_v2, depth_v2 = _chain_has_attr(func, _V2_RISK_ATTR)
    legacy, cycle_legacy, depth_legacy = _chain_has_attr(func, _LEGACY_RISK_ATTR)
    return v2, legacy, cycle_v2 or cycle_legacy, max(depth_v2, depth_legacy)


def normalize_runtime_limits() -> None:
    try:
        cap = int(float(os.environ.get("NIJA_ZERO_SIGNAL_STREAK_CAP", "12") or 12))
    except Exception:
        cap = 12
    cap = min(max(cap, 2), 12)
    os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP"] = str(cap)

    try:
        stale = int(float(os.environ.get("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", "100") or 100))
    except Exception:
        stale = 100
    os.environ["NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD"] = str(max(cap + 1, stale))

    try:
        timeout = float(os.environ.get("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S", "120") or 120)
    except Exception:
        timeout = 120.0
    os.environ["NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S"] = str(max(timeout, 120.0))
    os.environ["NIJA_CORE_LOOP_PROGRESS_LIMITS_NORMALIZED"] = "1"


def audit() -> tuple[bool, dict[str, str]]:
    modules_ready, details = canonicalize_loaded_patch_modules()
    normalize_runtime_limits()
    ready = modules_ready

    alias = sys.modules.get(_RISK_ALIAS)
    canonical = sys.modules.get(_RISK_CANONICAL)
    same = alias is canonical and isinstance(canonical, ModuleType)
    marker = str(getattr(canonical, "_MARKER", "") or "") if same else "identity_mismatch"
    details["downstream_risk_module"] = f"same={same};marker={marker or 'missing'}"
    ready = ready and same and marker == _REQUIRED_RISK_MARKER

    pipeline = sys.modules.get("bot.execution_pipeline") or sys.modules.get("execution_pipeline")
    if isinstance(pipeline, ModuleType):
        cls = getattr(pipeline, "ExecutionPipeline", None)
        execute = getattr(cls, "execute", None) if isinstance(cls, type) else None
        v2, legacy, cycle, depth = _wrapper_chain_status(execute)
        details["execution_pipeline_chain"] = (
            f"v2={v2};legacy={legacy};cycle={cycle};depth={depth}"
        )
        ready = ready and v2 and not legacy and not cycle
        if legacy or cycle or not v2:
            os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] = "0"

    core = sys.modules.get("bot.nija_core_loop") or sys.modules.get("nija_core_loop")
    if isinstance(core, ModuleType):
        cls = getattr(core, "NijaCoreLoop", None)
        phase3 = getattr(cls, "_phase3_scan_and_enter", None) if isinstance(cls, type) else None
        capped, cap_cycle, cap_depth = _chain_has_attr(phase3, _ZERO_CAP_ATTR)
        state_repair, state_cycle, state_depth = _chain_has_attr(phase3, _ZERO_STATE_ATTR)
        cycle = cap_cycle or state_cycle
        details["zero_signal_streak_chain"] = (
            f"cap_guard={capped};state_repair={state_repair};cycle={cycle};"
            f"depth={max(cap_depth, state_depth)}"
        )
        ready = ready and capped and state_repair and not cycle
        if not state_repair or cycle:
            os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "0"

    os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] = "1" if ready else "0"
    return ready, details


def _watchdog() -> None:
    last_signature = ""
    while True:
        try:
            ready, details = audit()
            signature = f"{ready}:{details}"
            if signature != last_signature:
                last_signature = signature
                logger.log(
                    logging.INFO if ready else logging.CRITICAL,
                    "RUNTIME_MODULE_IDENTITY_AUDIT marker=%s ready=%s details=%s",
                    _MARKER,
                    str(ready).lower(),
                    details,
                )
        except Exception as exc:
            os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] = "0"
            logger.critical("RUNTIME_MODULE_IDENTITY_AUDIT_FAILED marker=%s error=%s", _MARKER, exc)
        time.sleep(max(2.0, float(os.environ.get("NIJA_MODULE_IDENTITY_AUDIT_S", "10") or 10)))


def install() -> None:
    global _STARTED
    with _LOCK:
        ready, details = audit()
        os.environ["NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED"] = "1"
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="RuntimeModuleIdentityGuard", daemon=True).start()
        logger.critical(
            "RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED marker=%s ready=%s limits=streak:%s,stale:%s,stall:%s details=%s",
            _MARKER,
            str(ready).lower(),
            os.environ.get("NIJA_ZERO_SIGNAL_STREAK_CAP"),
            os.environ.get("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD"),
            os.environ.get("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S"),
            details,
        )
        if _live() and not ready and any(
            isinstance(sys.modules.get(name), ModuleType)
            for name in ("bot.execution_pipeline", "execution_pipeline")
        ):
            logger.critical(
                "RUNTIME_MODULE_IDENTITY_UNSAFE marker=%s action=release_manifest_fail_closed",
                _MARKER,
            )


def install_import_hook() -> None:
    install()


__all__ = [
    "install",
    "install_import_hook",
    "audit",
    "canonicalize_loaded_patch_modules",
    "recover_unregistered_patch_modules_from_threads",
    "normalize_runtime_limits",
    "_chain_has_attr",
    "_wrapper_chain_status",
]
