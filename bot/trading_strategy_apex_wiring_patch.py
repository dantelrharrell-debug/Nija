"""Repair TradingStrategy APEX/CoreLoop wiring before live cycles.

This patch is wiring-only: it adds the bot package directory to sys.path early,
resolves NIJAApexStrategyV71, and hydrates missing TradingStrategy.apex and
nija_core_loop references before run_cycle delegates to the existing scanner.
It does not lower entry thresholds, bypass order gates, or submit orders.

20260709ah hardening: Railway logs showed the core loop blocking before
TradingStrategy.run_cycle() was called:

    RUN_CYCLE_BLOCKED_MISSING_REF reason=apex_is_None

The previous wrapper only hydrated inside TradingStrategy.run_cycle(), so it
never executed. This version also wraps TradingStrategy.__getattribute__ for the
`apex` and `nija_core_loop` attributes, allowing the core-loop preflight
`getattr(strategy, "apex", None)` call to hydrate the real APEX object before it
marks the cycle as missing/backref-blocked.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import queue
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.trading_strategy_apex_wiring")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_ORIGINAL_BUILTIN_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED = False
_MARKER = "20260709ah"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default) or default))
    except Exception:
        return default


def _raw_value(obj: Any, name: str, default: Any = None) -> Any:
    try:
        data = object.__getattribute__(obj, "__dict__")
        if isinstance(data, dict) and name in data:
            return data.get(name, default)
    except Exception:
        pass
    try:
        return object.__getattribute__(obj, name)
    except Exception:
        return default


def _raw_set(obj: Any, name: str, value: Any) -> None:
    object.__setattr__(obj, name, value)


def _hydrating(obj: Any) -> bool:
    return bool(_raw_value(obj, "_nija_apex_wiring_hydrating_20260709ah", False))


def _ensure_bot_dir_on_path() -> None:
    bot_dir = Path(__file__).resolve().parent
    repo_root = bot_dir.parent
    for path in (str(bot_dir), str(repo_root)):
        if path and path not in sys.path:
            sys.path.insert(0, path)
    logger.warning(
        "TRADING_STRATEGY_APEX_WIRING_PATH_READY marker=%s bot_dir=%s repo_root=%s",
        _MARKER,
        bot_dir,
        repo_root,
    )


def _resolve_apex_class() -> tuple[Any | None, str]:
    _ensure_bot_dir_on_path()
    errors: list[str] = []
    for mod_name in ("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"):
        try:
            module = importlib.import_module(mod_name)
            cls = getattr(module, "NIJAApexStrategyV71", None)
            if cls is not None:
                return cls, mod_name
            errors.append(f"{mod_name}:class_missing")
        except Exception as exc:
            errors.append(f"{mod_name}:{type(exc).__name__}:{exc}")
    logger.warning("TRADING_STRATEGY_APEX_WIRING_RESOLVE_FAILED marker=%s errors=%s", _MARKER, errors)
    return None, "; ".join(errors)


def _resolve_core_loop_factory() -> tuple[Any | None, str]:
    _ensure_bot_dir_on_path()
    errors: list[str] = []
    for mod_name in ("bot.nija_core_loop", "nija_core_loop"):
        try:
            module = importlib.import_module(mod_name)
            fn = getattr(module, "get_nija_core_loop", None)
            if callable(fn):
                return fn, mod_name
            errors.append(f"{mod_name}:factory_missing")
        except Exception as exc:
            errors.append(f"{mod_name}:{type(exc).__name__}:{exc}")
    return None, "; ".join(errors)


def _active_broker(strategy: Any, broker: Any | None = None) -> Any | None:
    if broker is not None:
        return broker
    cached = _raw_value(strategy, "broker", None)
    if cached is not None and getattr(cached, "connected", False):
        return cached
    resolver = _raw_value(strategy, "_get_active_broker", None)
    if callable(resolver):
        try:
            return resolver()
        except Exception as exc:
            logger.warning("TRADING_STRATEGY_APEX_WIRING active_broker_resolver_failed marker=%s err=%s", _MARKER, exc)
    return cached


def _adopt_existing_core_loop(strategy: Any) -> bool:
    """Adopt a published/singleton core loop if one already exists."""
    for mod_name in ("bot.nija_core_loop", "nija_core_loop"):
        try:
            module = importlib.import_module(mod_name)
        except Exception:
            continue
        for attr in ("_NIJA_CORE_LOOP", "NIJA_CORE_LOOP", "nija_core_loop", "core_loop", "_core_loop"):
            loop = getattr(module, attr, None)
            if loop is None:
                continue
            try:
                _raw_set(strategy, "nija_core_loop", loop)
                apex = getattr(loop, "apex", None)
                if apex is not None and _raw_value(strategy, "apex", None) is None:
                    _raw_set(strategy, "apex", apex)
                    _raw_set(strategy, "execution_engine", getattr(apex, "execution_engine", None))
                logger.critical(
                    "TRADING_STRATEGY_APEX_WIRING_EXISTING_CORE_ADOPTED marker=%s module=%s attr=%s loop=%s apex=%s",
                    _MARKER,
                    mod_name,
                    attr,
                    type(loop).__name__,
                    type(_raw_value(strategy, "apex", None)).__name__ if _raw_value(strategy, "apex", None) is not None else "None",
                )
                return True
            except Exception:
                pass
    return False


def _hydrate_strategy_wiring(strategy: Any, broker: Any | None = None, reason: str = "runtime") -> bool:
    if not _truthy("NIJA_TRADING_STRATEGY_APEX_BACKREF_REPAIR", "true"):
        return not _needs_hydration(strategy)
    if _hydrating(strategy):
        return not _needs_hydration(strategy)

    _ensure_bot_dir_on_path()
    _raw_set(strategy, "_nija_apex_wiring_hydrating_20260709ah", True)
    hydrated = False
    try:
        _adopt_existing_core_loop(strategy)

        active_broker = _active_broker(strategy, broker)
        if active_broker is not None:
            try:
                _raw_set(strategy, "broker", active_broker)
            except Exception:
                pass

        if _raw_value(strategy, "apex", None) is None:
            apex_cls, source = _resolve_apex_class()
            if apex_cls is not None:
                try:
                    apex = apex_cls(broker_client=active_broker)
                    _raw_set(strategy, "apex", apex)
                    _raw_set(strategy, "execution_engine", getattr(apex, "execution_engine", None))
                    hydrated = True
                    try:
                        module = sys.modules.get(getattr(strategy.__class__, "__module__", ""))
                        if isinstance(module, ModuleType):
                            setattr(module, "NIJAApexStrategyV71", apex_cls)
                            setattr(module, "_APEX_AVAILABLE", True)
                    except Exception:
                        pass
                    logger.critical(
                        "TRADING_STRATEGY_APEX_BACKREF_REPAIRED marker=%s surface=apex_hydrate reason=%s source=%s broker=%s",
                        _MARKER,
                        reason,
                        source,
                        type(active_broker).__name__ if active_broker is not None else "None",
                    )
                    print(
                        f"[NIJA-PRINT] TRADING_STRATEGY_APEX_BACKREF_REPAIRED marker={_MARKER} surface=apex_hydrate reason={reason}",
                        flush=True,
                    )
                except Exception as exc:
                    logger.warning("TRADING_STRATEGY_APEX_WIRING apex_init_failed marker=%s err=%s", _MARKER, exc)
            else:
                logger.warning("TRADING_STRATEGY_APEX_WIRING apex_unavailable marker=%s detail=%s", _MARKER, source)

        apex = _raw_value(strategy, "apex", None)
        if apex is not None:
            if active_broker is not None and hasattr(apex, "update_broker_client"):
                try:
                    apex.update_broker_client(active_broker)
                except Exception as exc:
                    logger.debug("TRADING_STRATEGY_APEX_WIRING apex_update_broker_failed err=%s", exc)
            elif active_broker is not None and getattr(apex, "broker_client", None) is not active_broker:
                try:
                    setattr(apex, "broker_client", active_broker)
                except Exception:
                    pass

            if _raw_value(strategy, "execution_engine", None) is None:
                try:
                    _raw_set(strategy, "execution_engine", getattr(apex, "execution_engine", None))
                except Exception:
                    pass

            core_loop = _raw_value(strategy, "nija_core_loop", None)
            if core_loop is None:
                factory, source = _resolve_core_loop_factory()
                if callable(factory):
                    try:
                        max_positions = int(os.environ.get("NIJA_MAX_POSITIONS", "5") or 5)
                        core_loop = factory(apex_strategy=apex, max_positions=max(1, max_positions))
                        _raw_set(strategy, "nija_core_loop", core_loop)
                        hydrated = True
                        logger.critical(
                            "TRADING_STRATEGY_APEX_BACKREF_REPAIRED marker=%s surface=core_loop_hydrate reason=%s source=%s loop=%s",
                            _MARKER,
                            reason,
                            source,
                            type(core_loop).__name__,
                        )
                        print(
                            f"[NIJA-PRINT] TRADING_STRATEGY_APEX_BACKREF_REPAIRED marker={_MARKER} surface=core_loop_hydrate reason={reason}",
                            flush=True,
                        )
                    except Exception as exc:
                        logger.warning("TRADING_STRATEGY_APEX_WIRING core_loop_init_failed marker=%s err=%s", _MARKER, exc)
                else:
                    logger.warning("TRADING_STRATEGY_APEX_WIRING core_loop_unavailable marker=%s detail=%s", _MARKER, source)

            core_loop = _raw_value(strategy, "nija_core_loop", None)
            if core_loop is not None and getattr(core_loop, "apex", None) is not apex:
                try:
                    core_loop.apex = apex
                    hydrated = True
                    logger.warning("TRADING_STRATEGY_APEX_WIRING_CORE_LOOP_APEX_RESYNCED marker=%s", _MARKER)
                except Exception:
                    pass

        apex_ok = _raw_value(strategy, "apex", None) is not None
        core_ok = _raw_value(strategy, "nija_core_loop", None) is not None
        if apex_ok and core_ok:
            logger.critical(
                "TRADING_STRATEGY_APEX_BACKREF_READY marker=%s reason=%s apex=%s core_loop=%s hydrated=%s",
                _MARKER,
                reason,
                type(_raw_value(strategy, "apex", None)).__name__,
                type(_raw_value(strategy, "nija_core_loop", None)).__name__,
                hydrated,
            )
        return bool(apex_ok and core_ok) or hydrated
    finally:
        try:
            _raw_set(strategy, "_nija_apex_wiring_hydrating_20260709ah", False)
        except Exception:
            pass


def _needs_hydration(strategy: Any) -> bool:
    return _raw_value(strategy, "apex", None) is None or _raw_value(strategy, "nija_core_loop", None) is None


def _bounded_hydrate_strategy_wiring(strategy: Any, broker: Any | None = None, reason: str = "runtime") -> bool:
    if not _needs_hydration(strategy):
        return True

    try:
        if _hydrate_strategy_wiring(strategy, broker=broker, reason=f"{reason}:sync") and not _needs_hydration(strategy):
            return True
    except Exception as exc:
        logger.warning("TRADING_STRATEGY_APEX_WIRING_SYNC_HYDRATE_ERROR marker=%s reason=%s err=%s", _MARKER, reason, exc)

    timeout_s = max(5.0, _float_env("NIJA_TRADING_STRATEGY_WIRING_TIMEOUT_S", 20.0))
    q: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            q.put(("result", _hydrate_strategy_wiring(strategy, broker=broker, reason=reason)))
        except BaseException as exc:
            q.put(("error", exc))

    threading.Thread(target=_runner, name="trading-strategy-wiring-hydration", daemon=True).start()
    try:
        kind, payload = q.get(timeout=timeout_s)
    except queue.Empty:
        logger.critical(
            "TRADING_STRATEGY_APEX_WIRING_HYDRATION_TIMEOUT marker=%s reason=%s timeout_s=%.2f apex=%s core_loop=%s degraded_run_cycle_blocked=True",
            _MARKER,
            reason,
            timeout_s,
            type(_raw_value(strategy, "apex", None)).__name__ if _raw_value(strategy, "apex", None) is not None else "None",
            type(_raw_value(strategy, "nija_core_loop", None)).__name__ if _raw_value(strategy, "nija_core_loop", None) is not None else "None",
        )
        print(
            f"[NIJA-PRINT] TRADING_STRATEGY_APEX_WIRING_HYDRATION_TIMEOUT marker={_MARKER} reason={reason} timeout_s={timeout_s:.2f} degraded_run_cycle_blocked=true",
            flush=True,
        )
        return not _needs_hydration(strategy)
    if kind == "error":
        logger.warning("TRADING_STRATEGY_APEX_WIRING_HYDRATION_ERROR marker=%s reason=%s err=%s", _MARKER, reason, payload)
        return False
    return bool(payload) and not _needs_hydration(strategy)


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False

    original_init = getattr(cls, "__init__", None)
    if callable(original_init) and not getattr(original_init, "_nija_apex_wiring_wrapped_20260709ah", False):
        def _patched_init(self, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            if _needs_hydration(self):
                _bounded_hydrate_strategy_wiring(self, reason="post_init")

        setattr(_patched_init, "_nija_apex_wiring_wrapped_20260709ah", True)
        setattr(cls, "__init__", _patched_init)

    original_ensure = getattr(cls, "_ensure_nija_wiring", None)
    if callable(original_ensure) and not getattr(original_ensure, "_nija_apex_wiring_ensure_wrapped_20260709ah", False):
        def _patched_ensure(self, *args: Any, **kwargs: Any):
            if _needs_hydration(self):
                _bounded_hydrate_strategy_wiring(self, reason="ensure_nija_wiring")
            return original_ensure(self, *args, **kwargs)

        setattr(_patched_ensure, "_nija_apex_wiring_ensure_wrapped_20260709ah", True)
        setattr(cls, "_ensure_nija_wiring", _patched_ensure)

    original_getattribute = getattr(cls, "__getattribute__", object.__getattribute__)
    if not getattr(original_getattribute, "_nija_apex_backref_getattribute_20260709ah", False):
        def _patched_getattribute(self, name: str):
            try:
                value = original_getattribute(self, name)
            except AttributeError:
                if name in {"apex", "nija_core_loop"} and not _hydrating(self):
                    _bounded_hydrate_strategy_wiring(self, reason=f"missing_attribute:{name}")
                    return original_getattribute(self, name)
                raise
            if (
                name in {"apex", "nija_core_loop"}
                and value is None
                and not _hydrating(self)
                and _truthy("NIJA_TRADING_STRATEGY_APEX_BACKREF_REPAIR", "true")
            ):
                _bounded_hydrate_strategy_wiring(self, reason=f"lazy_getattribute:{name}")
                try:
                    value = original_getattribute(self, name)
                except AttributeError:
                    value = None
            return value

        setattr(_patched_getattribute, "_nija_apex_backref_getattribute_20260709ah", True)
        setattr(cls, "__getattribute__", _patched_getattribute)

    original_run_cycle = getattr(cls, "run_cycle", None)
    if callable(original_run_cycle) and not getattr(original_run_cycle, "_nija_apex_wiring_wrapped_20260709ah", False):
        def _patched_run_cycle(self, broker: Any = None, user_mode: bool = False) -> int:
            if _needs_hydration(self):
                _bounded_hydrate_strategy_wiring(self, broker=broker, reason="pre_run_cycle")
            if _raw_value(self, "apex", None) is None or _raw_value(self, "nija_core_loop", None) is None:
                retry_s = max(3, _int_env("NIJA_TRADING_STRATEGY_WIRING_RETRY_INTERVAL_S", 10))
                logger.critical(
                    "TRADING_STRATEGY_APEX_WIRING_RUN_CYCLE_BLOCKED marker=%s apex=%s core_loop=%s action=return_short_retry retry_s=%s",
                    _MARKER,
                    type(_raw_value(self, "apex", None)).__name__ if _raw_value(self, "apex", None) is not None else "None",
                    type(_raw_value(self, "nija_core_loop", None)).__name__ if _raw_value(self, "nija_core_loop", None) is not None else "None",
                    retry_s,
                )
                print(
                    f"[NIJA-PRINT] TRADING_STRATEGY_APEX_WIRING_RUN_CYCLE_BLOCKED marker={_MARKER} apex={type(_raw_value(self, 'apex', None)).__name__ if _raw_value(self, 'apex', None) is not None else 'None'} core_loop={type(_raw_value(self, 'nija_core_loop', None)).__name__ if _raw_value(self, 'nija_core_loop', None) is not None else 'None'} retry_s={retry_s}",
                    flush=True,
                )
                return retry_s
            return int(original_run_cycle(self, broker=broker, user_mode=user_mode) or 150)

        setattr(_patched_run_cycle, "_nija_apex_wiring_wrapped_20260709ah", True)
        setattr(cls, "run_cycle", _patched_run_cycle)

    for attr in ("TRADING_STRATEGY", "strategy", "trading_strategy", "_published_strategy"):
        obj = getattr(module, attr, None)
        if obj is not None and type(obj).__name__ == "TradingStrategy":
            if _needs_hydration(obj):
                _bounded_hydrate_strategy_wiring(obj, reason=f"module_attr:{attr}")

    _PATCHED = True
    logger.warning("TRADING_STRATEGY_APEX_WIRING_PATCHED module=%s marker=%s lazy_getattribute=true", getattr(module, "__name__", "<unknown>"), _MARKER)
    print(f"[NIJA-PRINT] TRADING_STRATEGY_APEX_WIRING_PATCHED marker={_MARKER} lazy_getattribute=true", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE, _ORIGINAL_BUILTIN_IMPORT
    os.environ.setdefault("NIJA_TRADING_STRATEGY_WIRING_TIMEOUT_S", "20")
    os.environ.setdefault("NIJA_TRADING_STRATEGY_WIRING_RETRY_INTERVAL_S", "10")
    os.environ.setdefault("NIJA_TRADING_STRATEGY_APEX_BACKREF_REPAIR", "true")
    _ensure_bot_dir_on_path()
    _try_patch_loaded()

    if _ORIGINAL_IMPORT_MODULE is None:
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.trading_strategy", "trading_strategy"}:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]

    if _ORIGINAL_BUILTIN_IMPORT is None:
        _ORIGINAL_BUILTIN_IMPORT = builtins.__import__

        def _wrapped_builtin_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
            module = _ORIGINAL_BUILTIN_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            target_names = {name}
            if fromlist:
                target_names.add(f"{name}.{','.join(str(x) for x in fromlist)}")
            if str(name).endswith("trading_strategy") or name in {"bot.trading_strategy", "trading_strategy"}:
                _try_patch_loaded()
            return module

        builtins.__import__ = _wrapped_builtin_import

    logger.warning("TRADING_STRATEGY_APEX_WIRING_INSTALL_COMPLETE patched=%s marker=%s lazy_getattribute=true", _PATCHED, _MARKER)


def install() -> None:
    install_import_hook()
