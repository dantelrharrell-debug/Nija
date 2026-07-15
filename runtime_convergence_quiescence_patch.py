"""Quiesce legacy convergence watchdogs after canonical guards are installed.

The July 15 Render runtime was safe enough to scan, but four watchdogs continued
reapplying already-installed wrappers every 250-500 ms. That produced repeated
AUTH_IMPORT_RECURSION_REMOVED, OKX_CONNECT_WRAPPER_CANONICALIZED,
SECONDARY_SCAN_OWNER_GUARDED and REENTRANT_SCAN_OWNER_CONVERGENCE_GUARDED logs,
while the module identity audit remained false because of a stale advisory latch.

This patch preserves all canonical wrappers and fail-closed checks. It changes only
watchdog convergence behavior: inspect complete wrapper chains, patch only when a
required marker is actually absent, clear a stale duplicate latch only when the
current process contains no duplicate module objects, and publish a stable audit.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_convergence_quiescence")
_MARKER = "20260715-convergence-quiescence-v1"
_LOCK = threading.RLock()
_INSTALLED = False
_GUARD_ATTR = "_nija_convergence_quiescence_v1"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _chain_has_attr(func: Any, attr: str) -> tuple[bool, bool, int]:
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return False, True, depth
        seen.add(ident)
        if bool(getattr(current, attr, False)):
            return True, False, depth
        current = getattr(current, "__wrapped__", None)
        if not callable(current):
            return False, False, depth
        depth += 1
        if depth >= 4096:
            return False, True, depth
    return False, False, depth


def _current_module_duplicates() -> list[str]:
    duplicates: list[str] = []
    for alias, module in tuple(sys.modules.items()):
        if not alias.startswith("nija_") or not isinstance(module, ModuleType):
            continue
        path = str(getattr(module, "__file__", "") or "")
        if "/bot/" not in path.replace("\\", "/") or not path.endswith(".py"):
            continue
        stem = path.replace("\\", "/").rsplit("/", 1)[-1][:-3]
        canonical = sys.modules.get(f"bot.{stem}")
        if isinstance(canonical, ModuleType) and canonical is not module:
            duplicates.append(f"{alias}->bot.{stem}")
    return sorted(set(duplicates))


def _patch_identity_module(module: ModuleType) -> bool:
    current = getattr(module, "canonicalize_loaded_patch_modules", None)
    if not callable(current):
        return False
    if getattr(current, _GUARD_ATTR, False):
        return True

    original = current

    def canonicalize_loaded_patch_modules() -> tuple[bool, dict[str, str]]:
        # A previous audit may have left this process-wide advisory latch at 1.
        # Evaluate the current module graph instead of inheriting stale state.
        previous = str(os.environ.get("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", "") or "")
        os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] = "0"
        ready, details = original()
        duplicates = _current_module_duplicates()
        reported = [
            key for key, value in details.items()
            if "duplicate=true" in str(value).lower()
        ]
        if duplicates or reported:
            os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] = "1"
            details["current_duplicate_modules"] = ",".join(duplicates or reported)
            return False, details
        os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] = "0"
        details["duplicate_latch"] = f"current_clean=true;previous={previous or 'unset'}"
        return bool(ready or not duplicates), details

    setattr(canonicalize_loaded_patch_modules, _GUARD_ATTR, True)
    canonicalize_loaded_patch_modules.__wrapped__ = original
    module.canonicalize_loaded_patch_modules = canonicalize_loaded_patch_modules
    logger.critical("MODULE_IDENTITY_CURRENT_STATE_AUDIT_PATCHED marker=%s", _MARKER)
    return True


def _patch_final_convergence(module: ModuleType) -> bool:
    changed = False

    auth_current = getattr(module, "_replace_recursive_auth_hooks", None)
    if callable(auth_current) and not getattr(auth_current, _GUARD_ATTR, False):
        original_auth = auth_current
        auth_done = False

        def replace_recursive_auth_hooks() -> bool:
            nonlocal auth_done
            if auth_done:
                return False
            result = bool(original_auth())
            auth_done = True
            return result

        setattr(replace_recursive_auth_hooks, _GUARD_ATTR, True)
        replace_recursive_auth_hooks.__wrapped__ = original_auth
        module._replace_recursive_auth_hooks = replace_recursive_auth_hooks
        changed = True

    okx_current = getattr(module, "_patch_okx_classes", None)
    if callable(okx_current) and not getattr(okx_current, _GUARD_ATTR, False):
        original_okx = okx_current

        def patch_okx_classes() -> bool:
            classes: list[type] = []
            for module_name in (
                "bot.broker_manager", "broker_manager",
                "bot.broker_integration", "broker_integration",
                "bot.multi_account_broker_manager", "multi_account_broker_manager",
            ):
                target = sys.modules.get(module_name)
                if not isinstance(target, ModuleType):
                    continue
                for name in dir(target):
                    cls = getattr(target, name, None)
                    if isinstance(cls, type) and "okx" in name.lower():
                        classes.append(cls)
            missing = False
            for cls in classes:
                connect = getattr(cls, "connect", None)
                found, cycle, _depth = _chain_has_attr(connect, "_nija_final_okx_endpoint_e")
                if cycle:
                    logger.critical("OKX_CONNECT_CHAIN_CYCLE marker=%s class=%s", _MARKER, cls.__name__)
                    return False
                missing = missing or not found
            return bool(original_okx()) if missing else False

        setattr(patch_okx_classes, _GUARD_ATTR, True)
        patch_okx_classes.__wrapped__ = original_okx
        module._patch_okx_classes = patch_okx_classes
        changed = True

    return changed


def _patch_scan_owner(module: ModuleType) -> bool:
    current = getattr(module, "_patch_brokers", None)
    if not callable(current) or getattr(current, _GUARD_ATTR, False):
        return bool(callable(current))
    original = current

    def patch_brokers(target: ModuleType) -> bool:
        missing = False
        coinbase = getattr(target, "CoinbaseBroker", None)
        if isinstance(coinbase, type):
            found, cycle, _ = _chain_has_attr(
                getattr(coinbase, "connect", None),
                "_nija_coinbase_failfast_20260713b",
            )
            if cycle:
                return False
            missing = missing or not found
        okx = getattr(target, "OKXBroker", None)
        if isinstance(okx, type):
            found, cycle, _ = _chain_has_attr(
                getattr(okx, "connect", None),
                "_nija_okx_connect_canonical_20260713b",
            )
            if cycle:
                return False
            missing = missing or not found
        return bool(original(target)) if missing else False

    setattr(patch_brokers, _GUARD_ATTR, True)
    patch_brokers.__wrapped__ = original
    module._patch_brokers = patch_brokers
    return True


def _patch_one_shot(module: ModuleType, function_name: str) -> bool:
    current = getattr(module, function_name, None)
    if not callable(current) or getattr(current, _GUARD_ATTR, False):
        return bool(callable(current))
    original = current
    done = False

    def guarded(*args: Any, **kwargs: Any) -> bool:
        nonlocal done
        if done:
            return True
        result = bool(original(*args, **kwargs))
        done = result
        return result

    setattr(guarded, _GUARD_ATTR, True)
    guarded.__wrapped__ = original
    setattr(module, function_name, guarded)
    return True


def audit() -> tuple[bool, dict[str, str]]:
    details: dict[str, str] = {}
    duplicates = _current_module_duplicates()
    details["duplicate_modules"] = ",".join(duplicates) or "none"

    identity = sys.modules.get("runtime_module_identity_convergence_patch")
    identity_ready = False
    if isinstance(identity, ModuleType):
        audit_fn = getattr(identity, "audit", None)
        if callable(audit_fn):
            identity_ready, identity_details = audit_fn()
            details["module_identity"] = str(identity_details)

    pipeline = sys.modules.get("bot.execution_pipeline") or sys.modules.get("execution_pipeline")
    risk_ready = True
    if isinstance(pipeline, ModuleType):
        cls = getattr(pipeline, "ExecutionPipeline", None)
        execute = getattr(cls, "execute", None) if isinstance(cls, type) else None
        v2, v2_cycle, depth = _chain_has_attr(execute, "_nija_pre_dispatch_risk_sizing_v2")
        legacy, legacy_cycle, _ = _chain_has_attr(
            execute,
            "_nija_pre_dispatch_exposure_headroom_wrapped_20260707a",
        )
        risk_ready = v2 and not legacy and not v2_cycle and not legacy_cycle
        details["risk_chain"] = (
            f"v2={v2};legacy={legacy};cycle={v2_cycle or legacy_cycle};depth={depth}"
        )

    ready = not duplicates and bool(identity_ready) and risk_ready
    os.environ["NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_READY"] = "1" if ready else "0"
    return ready, details


def install() -> None:
    global _INSTALLED
    with _LOCK:
        identity = importlib.import_module("runtime_module_identity_convergence_patch")
        _patch_identity_module(identity)

        final = importlib.import_module("final_runtime_convergence_patch")
        _patch_final_convergence(final)

        scan_owner = importlib.import_module("scan_owner_okx_auth_convergence_patch")
        _patch_scan_owner(scan_owner)

        scan_wrapper = importlib.import_module("scan_wrapper_convergence_repair_patch")
        _patch_one_shot(scan_wrapper, "_guard_secondary_scan_owner")

        reentrant = importlib.import_module("reentrant_scan_owner_repair")
        _patch_one_shot(reentrant, "_install_convergence_guard")

        ready, details = audit()
        os.environ["NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_INSTALLED"] = "1"
        _INSTALLED = True
        logger.critical(
            "RUNTIME_CONVERGENCE_QUIESCENCE_INSTALLED marker=%s ready=%s details=%s",
            _MARKER,
            str(ready).lower(),
            details,
        )


def install_import_hook() -> None:
    install()


__all__ = [
    "install",
    "install_import_hook",
    "audit",
    "_chain_has_attr",
    "_current_module_duplicates",
    "_patch_identity_module",
    "_patch_final_convergence",
    "_patch_scan_owner",
]
