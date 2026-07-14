"""Canonicalize startup patch modules before live trading imports begin.

sitecustomize historically loaded files from ``bot/`` under private ``nija_*``
aliases. Later runtime bootstraps imported the same files as ``bot.*``, executing
them twice and creating independent monitors and wrapper registries. This caused
alternating ExecutionPipeline wrappers, unbounded zero-signal streaks and duplicate
recovery threads.
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
_MARKER = "20260714-module-identity-v1"
_LOCK = threading.RLock()
_STARTED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LEGACY_RISK_ATTR = "_nija_pre_dispatch_exposure_headroom_wrapped_20260707a"
_V2_RISK_ATTR = "_nija_pre_dispatch_risk_sizing_v2"


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _live() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _bot_canonical_name(module: ModuleType) -> str:
    path = str(getattr(module, "__file__", "") or "")
    if not path:
        return ""
    resolved = Path(path)
    if resolved.suffix != ".py" or resolved.parent.name != "bot":
        return ""
    return f"bot.{resolved.stem}"


def _module_quality(module: ModuleType) -> tuple[int, int]:
    marker = str(getattr(module, "_MARKER", "") or "")
    score = 0
    if "downstream-risk-v2" in marker:
        score += 100
    if callable(getattr(module, "install_import_hook", None)):
        score += 10
    if callable(getattr(module, "install", None)):
        score += 5
    return score, len(vars(module))


def canonicalize_loaded_patch_modules() -> tuple[bool, dict[str, str]]:
    details: dict[str, str] = {}
    ready = True
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
            logger.critical(
                "DUPLICATE_PATCH_MODULE_CONVERGED marker=%s canonical=%s alias=%s selected_marker=%s",
                _MARKER,
                canonical,
                alias,
                getattr(selected, "_MARKER", "unknown"),
            )
        sys.modules[canonical] = selected
        sys.modules[alias] = selected
        details[canonical] = "same_object"
    return ready, details


def _wrapper_chain_status(func: Any) -> tuple[bool, bool, bool, int]:
    current = func
    seen: set[int] = set()
    legacy = current_v2 = cycle = False
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            cycle = True
            break
        seen.add(ident)
        legacy = legacy or bool(getattr(current, _LEGACY_RISK_ATTR, False))
        current_v2 = current_v2 or bool(getattr(current, _V2_RISK_ATTR, False))
        nxt = getattr(current, "__wrapped__", None)
        if not callable(nxt):
            break
        current = nxt
        depth += 1
        if depth >= 4096:
            cycle = True
            break
    return current_v2, legacy, cycle, depth


def normalize_runtime_limits() -> None:
    try:
        cap = int(float(os.environ.get("NIJA_ZERO_SIGNAL_STREAK_CAP", "12") or 12))
    except Exception:
        cap = 12
    os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP"] = str(min(max(cap, 2), 12))

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

    alias = sys.modules.get("nija_downstream_risk_governor_equity_repair_patch")
    canonical = sys.modules.get("bot.downstream_risk_governor_equity_repair_patch")
    if alias is not None or canonical is not None:
        same = alias is canonical and isinstance(canonical, ModuleType)
        marker = str(getattr(canonical, "_MARKER", "") or "") if same else "identity_mismatch"
        details["downstream_risk_module"] = f"same={same};marker={marker or 'missing'}"
        ready = ready and same and marker == "20260714-downstream-risk-v2"

    pipeline = sys.modules.get("bot.execution_pipeline") or sys.modules.get("execution_pipeline")
    if isinstance(pipeline, ModuleType):
        cls = getattr(pipeline, "ExecutionPipeline", None)
        execute = getattr(cls, "execute", None) if isinstance(cls, type) else None
        v2, legacy, cycle, depth = _wrapper_chain_status(execute)
        details["execution_pipeline_chain"] = (
            f"v2={v2};legacy={legacy};cycle={cycle};depth={depth}"
        )
        ready = ready and v2 and not legacy and not cycle
        if legacy or cycle:
            os.environ["NIJA_PRE_DISPATCH_RISK_SIZING_READY"] = "0"

    core = sys.modules.get("bot.nija_core_loop") or sys.modules.get("nija_core_loop")
    if isinstance(core, ModuleType):
        cls = getattr(core, "NijaCoreLoop", None)
        phase3 = getattr(cls, "_phase3_scan_and_enter", None) if isinstance(cls, type) else None
        capped = bool(getattr(phase3, "_nija_zero_streak_cap_e", False))
        details["zero_signal_streak_guard"] = f"installed={capped}"
        ready = ready and capped

    os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] = "1" if ready else "0"
    return ready, details


def _watchdog() -> None:
    while True:
        try:
            ready, details = audit()
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
            "RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED marker=%s ready=%s limits=streak:%s,stall:%s details=%s",
            _MARKER,
            str(ready).lower(),
            os.environ.get("NIJA_ZERO_SIGNAL_STREAK_CAP"),
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
    "normalize_runtime_limits",
    "_wrapper_chain_status",
]
