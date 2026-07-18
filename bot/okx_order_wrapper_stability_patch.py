"""Freeze canonical OKX order wrappers after their first successful install.

Legacy import/monitor hooks can alternately replace the same methods, causing the
final-submit and instId patches to wrap each other repeatedly. This module installs
both once, marks the class surfaces as stable, and replaces their patch entrypoints
with class-marker-aware delegates. Broker authentication and order validation remain
unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger("nija.okx_order_wrapper_stability")
_MARKER = "20260718-okx-wrapper-stability-v1"
_CLASS_MARKER = "_nija_okx_order_wrapper_chain_stable_v1"
_LOCK = threading.RLock()
_INSTALLED = False


def _candidate_classes(module: Any) -> list[type]:
    fn = getattr(module, "_candidate_order_classes", None)
    if callable(fn):
        found: list[type] = []
        for target_name in ("bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"):
            try:
                target = importlib.import_module(target_name)
            except Exception:
                continue
            try:
                for cls in fn(target):
                    if isinstance(cls, type) and cls not in found:
                        found.append(cls)
            except Exception:
                continue
        return found
    return []


def _freeze_module(module: Any) -> bool:
    original_wrap = getattr(module, "_wrap_order_class", None)
    if not callable(original_wrap) or getattr(original_wrap, "_nija_okx_stability_guard", False):
        return False

    @wraps(original_wrap)
    def stable_wrap(cls: type, module_name: str) -> bool:
        if bool(getattr(cls, _CLASS_MARKER, False)):
            return False
        changed = bool(original_wrap(cls, module_name))
        # Mark only after the module has had an opportunity to install its wrappers.
        if changed or any(
            bool(getattr(getattr(cls, name, None), attr, False))
            for name in ("place_market_order", "execute_order", "place_order")
            for attr in (
                "_nija_okx_final_order_submission_bridge_order_v20260709d",
                "_nija_okx_order_instid_payload_repair_order_v20260705f",
            )
        ):
            setattr(cls, _CLASS_MARKER, True)
        return changed

    stable_wrap._nija_okx_stability_guard = True
    stable_wrap.__wrapped__ = original_wrap
    module._wrap_order_class = stable_wrap
    return True


def _install_once() -> bool:
    modules = []
    for name in (
        "bot.okx_order_instid_payload_repair_patch",
        "bot.okx_final_order_submission_bridge_patch",
    ):
        modules.append(importlib.import_module(name))

    # First allow both canonical modules to install their current wrappers.
    for module in modules:
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()

    # Then freeze future watchdog/import-hook passes at the class level.
    changed = False
    for module in modules:
        changed = _freeze_module(module) or changed
        for cls in _candidate_classes(module):
            setattr(cls, _CLASS_MARKER, True)

    os.environ["NIJA_OKX_ORDER_WRAPPER_STABILITY_INSTALLED"] = "1"
    logger.critical(
        "OKX_ORDER_WRAPPER_CHAIN_STABLE marker=%s modules=%s class_marker=%s",
        _MARKER,
        ",".join(getattr(module, "__name__", "unknown") for module in modules),
        _CLASS_MARKER,
    )
    return changed or True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        result = _install_once()
        _INSTALLED = True
        return result


__all__ = ["install", "_freeze_module"]
