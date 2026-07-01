"""Repair TradingStrategy APEX/CoreLoop wiring before live cycles.

Latest Railway logs proved TradingLoop and TradingStrategy.run_cycle() are now
entered, but the cycle returns immediately when TradingStrategy was imported
without NIJAApexStrategyV71 available. In that state both ``self.apex`` and
``self.nija_core_loop`` are None, so no scan, signal, or order path can run.

This patch is wiring-only: it adds the bot package directory to sys.path early,
resolves NIJAApexStrategyV71, and hydrates missing TradingStrategy.apex and
nija_core_loop references before run_cycle delegates to the existing scanner.
It does not lower entry thresholds, bypass order gates, or submit orders.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.trading_strategy_apex_wiring")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False


def _ensure_bot_dir_on_path() -> None:
    bot_dir = Path(__file__).resolve().parent
    repo_root = bot_dir.parent
    for path in (str(bot_dir), str(repo_root)):
        if path and path not in sys.path:
            sys.path.insert(0, path)
    logger.warning(
        "TRADING_STRATEGY_APEX_WIRING_PATH_READY bot_dir=%s repo_root=%s",
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
    logger.warning("TRADING_STRATEGY_APEX_WIRING_RESOLVE_FAILED errors=%s", errors)
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
    try:
        cached = getattr(strategy, "broker", None)
        if cached is not None and getattr(cached, "connected", False):
            return cached
    except Exception:
        pass
    resolver = getattr(strategy, "_get_active_broker", None)
    if callable(resolver):
        try:
            return resolver()
        except Exception as exc:
            logger.warning("TRADING_STRATEGY_APEX_WIRING active_broker_resolver_failed err=%s", exc)
    return None


def _hydrate_strategy_wiring(strategy: Any, broker: Any | None = None, reason: str = "runtime") -> bool:
    _ensure_bot_dir_on_path()
    hydrated = False

    active_broker = _active_broker(strategy, broker)
    if active_broker is not None:
        try:
            strategy.broker = active_broker
        except Exception:
            pass

    if getattr(strategy, "apex", None) is None:
        apex_cls, source = _resolve_apex_class()
        if apex_cls is not None:
            try:
                strategy.apex = apex_cls(broker_client=active_broker)
                strategy.execution_engine = getattr(strategy.apex, "execution_engine", None)
                hydrated = True
                try:
                    module = sys.modules.get(getattr(strategy.__class__, "__module__", ""))
                    if isinstance(module, ModuleType):
                        setattr(module, "NIJAApexStrategyV71", apex_cls)
                        setattr(module, "_APEX_AVAILABLE", True)
                except Exception:
                    pass
                logger.critical(
                    "TRADING_STRATEGY_APEX_WIRING_APEX_HYDRATED reason=%s source=%s broker=%s",
                    reason,
                    source,
                    type(active_broker).__name__ if active_broker is not None else "None",
                )
            except Exception as exc:
                logger.warning("TRADING_STRATEGY_APEX_WIRING apex_init_failed err=%s", exc)
        else:
            logger.warning("TRADING_STRATEGY_APEX_WIRING apex_unavailable detail=%s", source)

    apex = getattr(strategy, "apex", None)
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

        if getattr(strategy, "execution_engine", None) is None:
            try:
                strategy.execution_engine = getattr(apex, "execution_engine", None)
            except Exception:
                pass

        if getattr(strategy, "nija_core_loop", None) is None:
            factory, source = _resolve_core_loop_factory()
            if callable(factory):
                try:
                    max_positions = int(os.environ.get("NIJA_MAX_POSITIONS", "5") or 5)
                    strategy.nija_core_loop = factory(
                        apex_strategy=apex,
                        max_positions=max(1, max_positions),
                    )
                    hydrated = True
                    logger.critical(
                        "TRADING_STRATEGY_APEX_WIRING_CORE_LOOP_HYDRATED reason=%s source=%s loop=%s",
                        reason,
                        source,
                        type(strategy.nija_core_loop).__name__,
                    )
                except Exception as exc:
                    logger.warning("TRADING_STRATEGY_APEX_WIRING core_loop_init_failed err=%s", exc)
            else:
                logger.warning("TRADING_STRATEGY_APEX_WIRING core_loop_unavailable detail=%s", source)

        core_loop = getattr(strategy, "nija_core_loop", None)
        if core_loop is not None and getattr(core_loop, "apex", None) is not apex:
            try:
                core_loop.apex = apex
                logger.warning("TRADING_STRATEGY_APEX_WIRING_CORE_LOOP_APEX_RESYNCED")
            except Exception:
                pass

    return bool(getattr(strategy, "apex", None) is not None and getattr(strategy, "nija_core_loop", None) is not None) or hydrated


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False

    original_init = getattr(cls, "__init__", None)
    if callable(original_init) and not getattr(original_init, "_nija_apex_wiring_wrapped", False):
        def _patched_init(self, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            _hydrate_strategy_wiring(self, reason="post_init")

        setattr(_patched_init, "_nija_apex_wiring_wrapped", True)
        setattr(cls, "__init__", _patched_init)

    original_run_cycle = getattr(cls, "run_cycle", None)
    if callable(original_run_cycle) and not getattr(original_run_cycle, "_nija_apex_wiring_wrapped", False):
        def _patched_run_cycle(self, broker: Any = None, user_mode: bool = False) -> int:
            _hydrate_strategy_wiring(self, broker=broker, reason="pre_run_cycle")
            if getattr(self, "apex", None) is None or getattr(self, "nija_core_loop", None) is None:
                logger.critical(
                    "TRADING_STRATEGY_APEX_WIRING_RUN_CYCLE_STILL_DEGRADED apex=%s core_loop=%s",
                    type(getattr(self, "apex", None)).__name__ if getattr(self, "apex", None) is not None else "None",
                    type(getattr(self, "nija_core_loop", None)).__name__ if getattr(self, "nija_core_loop", None) is not None else "None",
                )
            return int(original_run_cycle(self, broker=broker, user_mode=user_mode) or 150)

        setattr(_patched_run_cycle, "_nija_apex_wiring_wrapped", True)
        setattr(cls, "run_cycle", _patched_run_cycle)

    # If a singleton/object was already published, hydrate it now.
    for attr in ("TRADING_STRATEGY", "strategy", "trading_strategy", "_published_strategy"):
        obj = getattr(module, attr, None)
        if obj is not None and type(obj).__name__ == "TradingStrategy":
            _hydrate_strategy_wiring(obj, reason=f"module_attr:{attr}")

    _PATCHED = True
    logger.warning("TRADING_STRATEGY_APEX_WIRING_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    _ensure_bot_dir_on_path()
    _try_patch_loaded()
    if _ORIGINAL_IMPORT_MODULE is not None:
        logger.warning("TRADING_STRATEGY_APEX_WIRING_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
        return

    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if name in {"bot.trading_strategy", "trading_strategy"}:
            _install_on_module(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning("TRADING_STRATEGY_APEX_WIRING_INSTALL_COMPLETE patched=%s", _PATCHED)
