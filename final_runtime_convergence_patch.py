"""One-shot compatibility layer for NIJA runtime convergence.

Legacy versions started a 250 ms watchdog that repeatedly rewrote live methods.
This version performs the safe repairs once and delegates scan ownership to the
single canonical scan wrapper.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from types import ModuleType, SimpleNamespace
from typing import Any

logger = logging.getLogger("nija.final_runtime_convergence")
MARKER = "20260713f"
_LOCK = threading.RLock()
_PATCHED = False
_INSTALLING = False


def _auth_module() -> ModuleType | None:
    module = sys.modules.get("broker_auth_recovery_patch")
    return module if isinstance(module, ModuleType) else None


def _set_okx_endpoint(instance: Any, url: str) -> None:
    normalized = str(url or "").strip().rstrip("/")
    if not normalized:
        return
    os.environ["OKX_BASE_URL"] = normalized
    for attr in ("base_url", "api_base_url", "endpoint", "api_url", "rest_url"):
        try:
            if hasattr(instance, attr):
                setattr(instance, attr, normalized)
        except Exception:
            pass


def _safe_normalize(venue: str, instance: Any | None = None) -> None:
    auth = _auth_module()
    if auth is None:
        return
    normalizer = getattr(auth, f"normalize_{venue}_environment", None)
    if callable(normalizer):
        normalizer()
    if venue == "okx" and instance is not None:
        _set_okx_endpoint(instance, os.environ.get("OKX_BASE_URL", ""))


def _restore_importlib() -> bool:
    legacy = sys.modules.get("runtime_convergence_hardening_patch")
    original = getattr(legacy, "_ORIGINAL_IMPORT", None) if isinstance(legacy, ModuleType) else None
    if callable(original) and importlib.import_module is not original:
        importlib.import_module = original  # type: ignore[assignment]
        logger.warning("GLOBAL_IMPORTLIB_WRAPPER_REMOVED marker=%s", MARKER)
        return True
    return False


def _replace_recursive_auth_hooks() -> bool:
    changed = _restore_importlib()
    legacy = sys.modules.get("runtime_convergence_hardening_patch")
    if isinstance(legacy, ModuleType):
        setattr(legacy, "_WATCHDOG_STARTED", False)
        changed = True
    v2 = sys.modules.get("runtime_convergence_v2_patch")
    if isinstance(v2, ModuleType):
        setattr(v2, "_STARTED", False)
        changed = True
    if changed:
        logger.warning("AUTH_IMPORT_RECURSION_REMOVED marker=%s watchdog=false", MARKER)
    return changed


def _duplicate_result() -> SimpleNamespace:
    return SimpleNamespace(
        symbols_scored=0,
        entries_taken=0,
        entries_blocked=1,
        exits_taken=0,
        next_interval=max(5, int(float(os.getenv("NIJA_DUPLICATE_SCAN_NEXT_INTERVAL_S", "15") or 15))),
        errors=["duplicate_scan_suppressed"],
        metadata={"duplicate_scan": True},
    )


def _coerce_scan_result(result: Any) -> Any:
    if result is None:
        return _duplicate_result()
    if isinstance(result, tuple):
        scored = int(result[0] or 0) if len(result) > 0 else 0
        blocked = int(result[1] or 0) if len(result) > 1 else 0
        entered = int(result[2] or 0) if len(result) > 2 else 0
        meta = result[3] if len(result) > 3 and isinstance(result[3], dict) else {}
        return SimpleNamespace(
            symbols_scored=scored,
            entries_taken=entered,
            entries_blocked=blocked,
            exits_taken=int(meta.get("exits_taken", 0) or 0),
            next_interval=int(meta.get("next_interval", 15) or 15),
            errors=list(meta.get("errors", [])),
            metadata=meta,
        )
    required = ("symbols_scored", "entries_taken", "entries_blocked", "exits_taken", "next_interval")
    return result if all(hasattr(result, field) for field in required) else _duplicate_result()


def _patch_core_loop(module: ModuleType) -> bool:
    try:
        import scan_wrapper_convergence_repair_patch as canonical
        return bool(canonical._patch_core_loop(module))
    except Exception as exc:
        logger.error("CANONICAL_SCAN_PATCH_FAILED marker=%s error=%s", MARKER, exc)
        return False


def _patch_okx_classes() -> bool:
    try:
        import scan_owner_okx_auth_convergence_patch as broker_patch
    except Exception:
        return False
    changed = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = bool(broker_patch._patch_brokers(module)) or changed
    return changed


def _patch_loaded() -> bool:
    changed = _replace_recursive_auth_hooks()
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_core_loop(module) or changed
    changed = _patch_okx_classes() or changed
    return changed


def install() -> bool:
    global _PATCHED, _INSTALLING
    with _LOCK:
        if _PATCHED:
            return True
        if _INSTALLING:
            return False
        _INSTALLING = True
        try:
            _replace_recursive_auth_hooks()
            _PATCHED = True
            os.environ["NIJA_FINAL_RUNTIME_CONVERGENCE_INSTALLED"] = "1"
            os.environ["NIJA_RUNTIME_CONVERGENCE_WATCHDOGS_DISABLED"] = "1"
            logger.warning("FINAL_RUNTIME_CONVERGENCE_INSTALLED marker=%s watchdog=false", MARKER)
            return True
        finally:
            _INSTALLING = False


def installed() -> bool:
    return _PATCHED


__all__ = ["install", "installed", "_coerce_scan_result", "_duplicate_result", "_patch_core_loop", "_set_okx_endpoint"]
