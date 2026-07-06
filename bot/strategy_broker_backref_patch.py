from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.strategy_broker_backref_patch")
_MARKER = "STRATEGY_BROKER_BACKREF_PATCHED marker=20260705a"
_PATCHED_ATTR = "_nija_strategy_broker_backref_20260705a"


def _set_ref(target: Any, attr: str, value: Any) -> None:
    if target is None or value is None:
        return
    try:
        if getattr(target, attr, None) is None:
            setattr(target, attr, value)
    except Exception:
        pass


def _wire(strategy: Any) -> None:
    apex = getattr(strategy, "apex", None)
    core = getattr(strategy, "nija_core_loop", None)
    for target in (apex, core):
        if target is None:
            continue
        _set_ref(target, "strategy", strategy)
        _set_ref(target, "trading_strategy", strategy)
        _set_ref(target, "broker_manager", getattr(strategy, "broker_manager", None))
        _set_ref(target, "multi_account_manager", getattr(strategy, "multi_account_manager", None))
        _set_ref(target, "multi_account_broker_manager", getattr(strategy, "multi_account_manager", None))
    logger.info(
        "STRATEGY_BROKER_BACKREF_WIRED marker=20260705a apex=%s core=%s",
        type(apex).__name__ if apex is not None else "None",
        type(core).__name__ if core is not None else "None",
    )


def _patch_class(cls: type) -> bool:
    patched = False
    original_ensure = getattr(cls, "_ensure_nija_wiring", None)
    if callable(original_ensure) and not getattr(original_ensure, _PATCHED_ATTR, False):
        @wraps(original_ensure)
        def ensure(self: Any, *args: Any, **kwargs: Any):
            result = original_ensure(self, *args, **kwargs)
            _wire(self)
            return result
        setattr(ensure, _PATCHED_ATTR, True)
        cls._ensure_nija_wiring = ensure
        patched = True

    original_run = getattr(cls, "run_cycle", None)
    if callable(original_run) and not getattr(original_run, _PATCHED_ATTR, False):
        @wraps(original_run)
        def run_cycle(self: Any, *args: Any, **kwargs: Any):
            _wire(self)
            result = original_run(self, *args, **kwargs)
            _wire(self)
            return result
        setattr(run_cycle, _PATCHED_ATTR, True)
        cls.run_cycle = run_cycle
        patched = True

    if patched:
        logger.warning("%s class=%s", _MARKER, cls.__name__)
        print("[NIJA-PRINT] STRATEGY_BROKER_BACKREF_PATCHED marker=20260705a", flush=True)
    return patched


def _patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if name.endswith("trading_strategy") and isinstance(module, ModuleType):
            cls = getattr(module, "TradingStrategy", None)
            if isinstance(cls, type):
                patched = _patch_class(cls) or patched
    return patched


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_STRATEGY_BROKER_BACKREF_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            _patch_loaded()
        except Exception as exc:
            logger.warning("STRATEGY_BROKER_BACKREF hook failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_STRATEGY_BROKER_BACKREF_HOOK", True)
    logger.warning("STRATEGY_BROKER_BACKREF_IMPORT_HOOK_INSTALLED marker=20260705a")


def install() -> None:
    install_import_hook()
