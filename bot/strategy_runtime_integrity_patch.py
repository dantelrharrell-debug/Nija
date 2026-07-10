from __future__ import annotations

import builtins
import importlib
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.strategy_runtime_integrity")
_MARKER = "20260709au"
_HOOK = "_NIJA_STRATEGY_RUNTIME_INTEGRITY_HOOK_20260709AU"
_WRAP_ATTR = "_nija_strategy_runtime_integrity_wrap_20260709au"
_ENSURE_ATTR = "_nija_strategy_runtime_integrity_ensure_20260709au"


def _raw_get(obj: Any, name: str, default: Any = None) -> Any:
    try:
        values = object.__getattribute__(obj, "__dict__")
        if isinstance(values, dict) and name in values:
            return values.get(name, default)
    except Exception:
        pass
    try:
        return object.__getattribute__(obj, name)
    except Exception:
        return default


def _raw_set(obj: Any, name: str, value: Any) -> None:
    try:
        object.__setattr__(obj, name, value)
    except Exception:
        setattr(obj, name, value)


def _is_wired(strategy: Any) -> bool:
    return _raw_get(strategy, "apex", None) is not None and _raw_get(strategy, "nija_core_loop", None) is not None


def _bind_broker(strategy: Any, broker: Any) -> None:
    _raw_set(strategy, "broker", broker)
    apex = _raw_get(strategy, "apex", None)
    if apex is not None:
        try:
            update = getattr(apex, "update_broker_client", None)
            if callable(update):
                update(broker)
            else:
                setattr(apex, "broker_client", broker)
        except Exception as exc:
            logger.warning("STRATEGY_RUNTIME_BROKER_BIND_APEX_FAILED marker=%s err=%s", _MARKER, exc)
    engine = _raw_get(strategy, "execution_engine", None)
    if engine is None and apex is not None:
        engine = getattr(apex, "execution_engine", None)
        if engine is not None:
            _raw_set(strategy, "execution_engine", engine)
    if engine is not None:
        try:
            setattr(engine, "broker_client", broker)
        except Exception:
            pass


def _repair_existing(strategy: Any, broker: Any) -> bool:
    if strategy is None:
        return False
    _bind_broker(strategy, broker)
    if _is_wired(strategy):
        return True

    ensure = getattr(strategy, "_ensure_nija_wiring", None)
    if callable(ensure):
        try:
            ensure()
        except Exception as exc:
            logger.warning("STRATEGY_RUNTIME_EXISTING_ENSURE_FAILED marker=%s err=%s", _MARKER, exc)
    if _is_wired(strategy):
        _bind_broker(strategy, broker)
        return True

    for module_name in ("bot.trading_strategy_apex_wiring_patch", "trading_strategy_apex_wiring_patch"):
        try:
            module = importlib.import_module(module_name)
            hydrate = getattr(module, "_bounded_hydrate_strategy_wiring", None)
            if callable(hydrate):
                hydrate(strategy, broker=broker, reason="strategy_runtime_integrity")
        except Exception as exc:
            logger.debug("STRATEGY_RUNTIME_HYDRATOR_UNAVAILABLE marker=%s module=%s err=%s", _MARKER, module_name, exc)
        if _is_wired(strategy):
            _bind_broker(strategy, broker)
            return True
    return False


def _patch_module(module: ModuleType) -> bool:
    original = getattr(module, "_wrap_broker_as_strategy", None)
    fallback_cls = getattr(module, "_BrokerRuntimeStrategy", None)
    if not callable(original):
        return False
    if getattr(original, _WRAP_ATTR, False):
        return True

    if isinstance(fallback_cls, type):
        original_ensure = getattr(fallback_cls, "_ensure_nija_wiring", None)
        if callable(original_ensure) and not getattr(original_ensure, _ENSURE_ATTR, False):
            @wraps(original_ensure)
            def _ensure_runtime(self: Any) -> None:
                if not _is_wired(self):
                    wire = getattr(self, "_wire_runtime", None)
                    if callable(wire):
                        wire()
                if not _is_wired(self):
                    original_ensure(self)

            setattr(_ensure_runtime, _ENSURE_ATTR, True)
            setattr(fallback_cls, "_ensure_nija_wiring", _ensure_runtime)

    @wraps(original)
    def _wrap_broker_as_complete_strategy(broker: Any) -> Any:
        strategy = original(broker)
        if _repair_existing(strategy, broker):
            logger.critical(
                "STRATEGY_RUNTIME_INTEGRITY_READY marker=%s strategy=%s apex=%s core=%s source=primary",
                _MARKER,
                type(strategy).__name__,
                type(_raw_get(strategy, "apex", None)).__name__,
                type(_raw_get(strategy, "nija_core_loop", None)).__name__,
            )
            return strategy

        if isinstance(fallback_cls, type):
            logger.critical(
                "STRATEGY_RUNTIME_INTEGRITY_FALLBACK marker=%s primary_strategy=%s reason=incomplete_apex_or_core",
                _MARKER,
                type(strategy).__name__ if strategy is not None else "None",
            )
            fallback = fallback_cls(broker)
            if _repair_existing(fallback, broker):
                logger.critical(
                    "STRATEGY_RUNTIME_INTEGRITY_READY marker=%s strategy=%s apex=%s core=%s source=fallback",
                    _MARKER,
                    type(fallback).__name__,
                    type(_raw_get(fallback, "apex", None)).__name__,
                    type(_raw_get(fallback, "nija_core_loop", None)).__name__,
                )
                print(
                    f"[NIJA-PRINT] STRATEGY_RUNTIME_INTEGRITY_READY marker={_MARKER} source=fallback "
                    f"strategy={type(fallback).__name__}",
                    flush=True,
                )
                return fallback

        raise RuntimeError(
            "STRATEGY_RUNTIME_INTEGRITY_FAILURE: unable to construct NIJA APEX/CoreLoop runtime; "
            "refusing to start a live loop that can only emit RUN_CYCLE_BLOCKED_MISSING_REF"
        )

    setattr(_wrap_broker_as_complete_strategy, _WRAP_ATTR, True)
    setattr(module, "_wrap_broker_as_strategy", _wrap_broker_as_complete_strategy)
    logger.warning("STRATEGY_RUNTIME_INTEGRITY_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _patch_loaded() -> bool:
    patched = False
    for name in ("bot.trading_engine_strategy_wrapper_patch", "trading_engine_strategy_wrapper_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("trading_engine_strategy_wrapper_patch"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK, True)
    logger.warning("STRATEGY_RUNTIME_INTEGRITY_INSTALL_COMPLETE marker=%s patched=%s", _MARKER, _patch_loaded())


def install() -> None:
    install_import_hook()
