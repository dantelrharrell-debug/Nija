"""Converge OKX order wrappers and downstream pre-trade risk deterministically.

Two legacy OKX patches protect different parts of the same order path:

* ``okx_final_order_submission_bridge_patch`` validates the final call shape.
* ``okx_order_instid_payload_repair_patch`` normalizes and validates ``instId``.

Both patches historically inspected only the outer function.  The final bridge also
unwrapped one layer before replacing a method, so the two import hooks could remove
and reinstall each other indefinitely.  This module makes both installers
chain-aware, preserves both layers, binds canonical/legacy module aliases to one
object, and heals late method replacement without log flooding.

The same convergence pass imports and patches ``PreTradeRiskEngine`` explicitly.
The downstream risk monitor previously waited only for an incidental import, which
left its required ``pretrade`` state false for the full monitor lifetime.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.okx_order_wrapper_stability")
_MARKER = "20260723-okx-wrapper-stability-v2"
_CLEANUP_MARKER = "20260723-runtime-error-cleanup-v1"
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_LAST_STATE = ""

_INSTID_CANONICAL = "bot.okx_order_instid_payload_repair_patch"
_INSTID_ALIAS = "okx_order_instid_payload_repair_patch"
_FINAL_CANONICAL = "bot.okx_final_order_submission_bridge_patch"
_FINAL_ALIAS = "okx_final_order_submission_bridge_patch"
_RISK_CANONICAL = "bot.downstream_risk_governor_equity_repair_patch"
_RISK_ALIAS = "nija_downstream_risk_governor_equity_repair_patch"
_PRETRADE_CANONICAL = "bot.pre_trade_risk_engine"
_PRETRADE_ALIAS = "pre_trade_risk_engine"

_INSTID_ATTR = "_nija_okx_order_instid_payload_repair_order_v20260705f"
_FINAL_ATTR = "_nija_okx_final_order_submission_bridge_order_v20260709d"
_GUARD_ATTR = "_nija_okx_wrapper_stability_guard_v2"
_CLASS_MARKER = "_nija_okx_order_wrapper_chain_stable_v2"
_ORDER_METHODS = ("place_market_order", "execute_order", "place_order")
_TARGET_MODULES = {
    "bot.broker_manager",
    "broker_manager",
    "bot.broker_integration",
    "broker_integration",
    "bot.multi_account_broker_manager",
    "multi_account_broker_manager",
    "bot.multi_broker_execution_router",
    "multi_broker_execution_router",
}


def _deployment_sha() -> str:
    for name in (
        "RENDER_GIT_COMMIT",
        "GIT_COMMIT_SHA",
        "GIT_COMMIT",
        "SOURCE_VERSION",
        "RAILWAY_GIT_COMMIT_SHA",
    ):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return "unknown"


def _chain_has_attr(func: Any, attr: str, *, max_depth: int = 256) -> tuple[bool, bool, int]:
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        identity = id(current)
        if identity in seen:
            return False, True, depth
        seen.add(identity)
        if bool(getattr(current, attr, False)):
            return True, False, depth
        current = getattr(current, "__wrapped__", None)
        if not callable(current):
            return False, False, depth
        depth += 1
        if depth >= max_depth:
            return False, True, depth
    return False, False, depth


def _bind_alias(canonical_name: str, alias_name: str) -> ModuleType:
    module = importlib.import_module(canonical_name)
    sys.modules[canonical_name] = module
    sys.modules[alias_name] = module
    return module


def _narrow_interesting(name: str) -> bool:
    return str(name or "").strip() in _TARGET_MODULES


def _propagate_chain_marker(func: Any, marker: str) -> bool:
    found, cycle, _depth = _chain_has_attr(func, marker)
    if cycle or not found or not callable(func):
        return found and not cycle
    if not bool(getattr(func, marker, False)):
        try:
            setattr(func, marker, True)
        except Exception:
            return False
    return True


def _guard_patch_module(module: ModuleType, marker: str) -> bool:
    current = getattr(module, "_wrap_order_class", None)
    if not callable(current):
        return False
    if bool(getattr(current, _GUARD_ATTR, False)):
        module._interesting_module = _narrow_interesting
        return True

    original = current

    @wraps(original)
    def stable_wrap(okx_cls: type, module_name: str) -> bool:
        # Propagate markers already present below a later outer wrapper so legacy
        # top-level checks cannot reinstall or discard an existing safety layer.
        for method_name in _ORDER_METHODS:
            method = getattr(okx_cls, method_name, None)
            if callable(method):
                _propagate_chain_marker(method, marker)
        changed = bool(original(okx_cls, module_name))
        for method_name in _ORDER_METHODS:
            method = getattr(okx_cls, method_name, None)
            if callable(method):
                _propagate_chain_marker(method, marker)
        return changed

    setattr(stable_wrap, _GUARD_ATTR, True)
    setattr(stable_wrap, "__wrapped__", original)
    module._wrap_order_class = stable_wrap
    module._interesting_module = _narrow_interesting
    return True


def _load_patch_modules() -> tuple[ModuleType, ModuleType]:
    instid = _bind_alias(_INSTID_CANONICAL, _INSTID_ALIAS)
    final = _bind_alias(_FINAL_CANONICAL, _FINAL_ALIAS)
    if not _guard_patch_module(final, _FINAL_ATTR):
        raise RuntimeError("final_okx_order_wrapper_guard_unavailable")
    if not _guard_patch_module(instid, _INSTID_ATTR):
        raise RuntimeError("instid_okx_order_wrapper_guard_unavailable")
    return instid, final


def _loaded_target_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    seen: set[int] = set()
    for name in _TARGET_MODULES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            modules.append(module)
    return modules


def _candidate_classes(module: ModuleType, targets: list[ModuleType]) -> list[type]:
    finder = getattr(module, "_candidate_order_classes", None)
    if not callable(finder):
        return []
    classes: list[type] = []
    seen: set[int] = set()
    for target in targets:
        try:
            candidates = finder(target)
        except Exception:
            logger.debug("OKX candidate scan failed module=%s", target.__name__, exc_info=True)
            continue
        for cls in candidates:
            if isinstance(cls, type) and id(cls) not in seen:
                seen.add(id(cls))
                classes.append(cls)
    return classes


def _class_state(cls: type) -> tuple[bool, dict[str, str]]:
    details: dict[str, str] = {}
    ready = True
    observed = False
    for method_name in _ORDER_METHODS:
        method = getattr(cls, method_name, None)
        if not callable(method):
            continue
        observed = True
        instid, instid_cycle, instid_depth = _chain_has_attr(method, _INSTID_ATTR)
        final, final_cycle, final_depth = _chain_has_attr(method, _FINAL_ATTR)
        cycle = instid_cycle or final_cycle
        method_ready = instid and final and not cycle
        details[method_name] = (
            f"instid={instid};final={final};cycle={cycle};"
            f"depth={max(instid_depth, final_depth)}"
        )
        ready = ready and method_ready
        if method_ready:
            _propagate_chain_marker(method, _INSTID_ATTR)
            _propagate_chain_marker(method, _FINAL_ATTR)
    if observed and ready:
        setattr(cls, _CLASS_MARKER, True)
    return observed and ready, details


def _install_patch_module(module: ModuleType) -> None:
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer):
        raise RuntimeError(f"{module.__name__}_installer_missing")
    installer()


def _ensure_okx_wrappers() -> tuple[bool, dict[str, str]]:
    instid, final = _load_patch_modules()

    # Install final-call validation first, then put instId normalization around it.
    # The chain-aware guards keep both layers present on subsequent import-hook runs.
    _install_patch_module(final)
    _install_patch_module(instid)

    targets = _loaded_target_modules()
    for target in targets:
        patch_final = getattr(final, "_patch_module", None)
        patch_instid = getattr(instid, "_patch_module", None)
        if callable(patch_final):
            patch_final(target)
        if callable(patch_instid):
            patch_instid(target)

    classes: list[type] = []
    seen: set[int] = set()
    for module in (final, instid):
        for cls in _candidate_classes(module, targets):
            if id(cls) not in seen:
                seen.add(id(cls))
                classes.append(cls)

    details: dict[str, str] = {}
    ready = bool(classes)
    for cls in classes:
        class_ready, class_details = _class_state(cls)
        ready = ready and class_ready
        label = f"{getattr(cls, '__module__', '')}.{getattr(cls, '__name__', '')}"
        details[label] = str(class_details)
    if not classes:
        details["classes"] = "not_loaded"
    os.environ["NIJA_OKX_ORDER_WRAPPER_STABILITY_READY"] = "1" if ready else "0"
    return ready, details


def _ensure_pretrade_risk() -> tuple[bool, str]:
    pretrade = _bind_alias(_PRETRADE_CANONICAL, _PRETRADE_ALIAS)
    risk = _bind_alias(_RISK_CANONICAL, _RISK_ALIAS)
    installer = getattr(risk, "_install_on_pre_trade_risk_engine", None)
    if not callable(installer):
        return False, "pretrade_installer_missing"
    ready = bool(installer(pretrade))
    full_install = getattr(risk, "install_import_hook", None) or getattr(risk, "install", None)
    if callable(full_install):
        full_install()
    state = getattr(risk, "_STATE", {})
    ready = ready and bool(state.get("pretrade", False))
    os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_READY"] = (
        "1" if all(bool(state.get(key, False)) for key in ("downstream", "pipeline", "pretrade", "taxonomy")) else "0"
    )
    return ready, str(state)


def _apply() -> tuple[bool, dict[str, str]]:
    okx_ready, okx_details = _ensure_okx_wrappers()
    pretrade_ready, pretrade_details = _ensure_pretrade_risk()
    ready = okx_ready and pretrade_ready
    os.environ["NIJA_OKX_ORDER_WRAPPER_STABILITY_INSTALLED"] = "1"
    os.environ["NIJA_RUNTIME_ERROR_CLEANUP_V1_INSTALLED"] = "1"
    os.environ["NIJA_RUNTIME_ERROR_CLEANUP_V1_READY"] = "1" if ready else "0"
    return ready, {
        "okx": str(okx_details),
        "pretrade": pretrade_details,
        "deployment_sha": _deployment_sha(),
    }


def _publish_state(ready: bool, details: dict[str, str]) -> None:
    global _LAST_STATE
    signature = f"{ready}:{details}"
    if signature == _LAST_STATE:
        return
    previous = _LAST_STATE
    _LAST_STATE = signature
    logger.log(
        logging.CRITICAL if ready else logging.WARNING,
        "RUNTIME_ERROR_CLEANUP_STATE marker=%s cleanup=%s ready=%s details=%s",
        _MARKER,
        _CLEANUP_MARKER,
        str(ready).lower(),
        details,
    )
    if ready and (not previous or not previous.startswith("True:")):
        logger.critical(
            "RUNTIME_ERROR_CLEANUP_READY marker=%s cleanup=%s commit=%s okx_wrapper_chain=stable pretrade_risk=ready",
            _MARKER,
            _CLEANUP_MARKER,
            _deployment_sha(),
        )


def _monitor_interval() -> float:
    try:
        return max(0.5, float(os.environ.get("NIJA_RUNTIME_ERROR_CLEANUP_MONITOR_S", "2.0") or 2.0))
    except Exception:
        return 2.0


def _monitor() -> None:
    while True:
        try:
            ready, details = _apply()
            _publish_state(ready, details)
        except Exception as exc:
            os.environ["NIJA_RUNTIME_ERROR_CLEANUP_V1_READY"] = "0"
            logger.warning(
                "RUNTIME_ERROR_CLEANUP_RETRY marker=%s cleanup=%s error=%s",
                _MARKER,
                _CLEANUP_MARKER,
                f"{type(exc).__name__}:{exc}",
                exc_info=True,
            )
        time.sleep(_monitor_interval())


def install() -> bool:
    global _INSTALLED, _MONITOR_STARTED
    with _LOCK:
        ready, details = _apply()
        _publish_state(ready, details)
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(
                target=_monitor,
                name="RuntimeErrorCleanupV1",
                daemon=True,
            ).start()
        _INSTALLED = True
        return ready


def installed_marker() -> str | None:
    return _MARKER if _INSTALLED else None


__all__ = [
    "install",
    "installed_marker",
    "_chain_has_attr",
    "_guard_patch_module",
    "_ensure_okx_wrappers",
    "_ensure_pretrade_risk",
    "_class_state",
    "_narrow_interesting",
]
