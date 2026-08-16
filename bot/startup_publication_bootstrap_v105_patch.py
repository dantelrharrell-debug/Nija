"""Converge canonical strategy publication and break capital bootstrap recursion.

Production logs on 2026-08-16 showed two remaining startup blockers after v104:

1. ``bot.trading_strategy`` could still remain partially initialized because
   additional optional broker/runtime dependencies were imported before the
   ``TradingStrategy`` class definition.
2. A successful CapitalAuthority refresh could synchronize platform connection
   state, fire ``MultiAccountBrokerManager._on_platform_ready()``, and re-enter
   ``refresh_capital_authority()`` recursively until ``RecursionError``.

v105 keeps all safety gates intact.  It only defers optional TradingStrategy
startup imports until after the canonical class is defined, then hydrates those
optional dependencies before the first TradingStrategy instance is initialized.
It also makes the platform-ready capital callback single-flight per manager so a
capital refresh cannot recursively trigger itself.

No broker connectivity, balance, position, strategy readiness, execution
authority, nonce, bootstrap, risk, or kill-switch state is synthesized.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.startup_publication_bootstrap_v105")
MARKER = "20260816-startup-publication-bootstrap-v105"
_LOCK = threading.RLock()
_INSTALLED = False
_HOOK_FLAG = "_NIJA_STARTUP_PUBLICATION_BOOTSTRAP_V105"
_ORIGINAL_ATTR = "_NIJA_STARTUP_PUBLICATION_BOOTSTRAP_V105_ORIGINAL"

_CALLERS = {"bot.trading_strategy", "trading_strategy"}
_DEFERRED_IMPORTS = {
    "bot.nija_apex_strategy_v71",
    "nija_apex_strategy_v71",
    "bot.nija_core_loop",
    "nija_core_loop",
    "bot.broker_manager",
    "broker_manager",
    "bot.multi_account_broker_manager",
    "multi_account_broker_manager",
    "bot.independent_broker_trader",
    "independent_broker_trader",
    "bot.pipeline_order_submitter",
    "pipeline_order_submitter",
    "bot.market_readiness_gate",
    "market_readiness_gate",
}


def _initializing(module: ModuleType | None) -> bool:
    return bool(
        isinstance(module, ModuleType)
        and getattr(getattr(module, "__spec__", None), "_initializing", False)
    )


def _caller_is_initializing(globals_dict: Any) -> tuple[bool, str]:
    if not isinstance(globals_dict, dict):
        return False, ""
    caller = str(globals_dict.get("__name__", "") or "")
    if caller not in _CALLERS:
        return False, caller
    return _initializing(sys.modules.get(caller)), caller


def _import_first(*names: str) -> ModuleType | None:
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


def _hydrate_strategy_dependencies(module: ModuleType) -> None:
    """Hydrate optional TradingStrategy globals after class publication."""
    apex = _import_first("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71")
    apex_cls = getattr(apex, "NIJAApexStrategyV71", None) if apex else None
    setattr(module, "NIJAApexStrategyV71", apex_cls)
    setattr(module, "_APEX_AVAILABLE", apex_cls is not None)

    broker = _import_first("bot.broker_manager", "broker_manager")
    if broker is not None:
        for name in ("BrokerType", "KrakenBroker", "CoinbaseBroker", "BaseBroker", "BrokerManager"):
            if hasattr(broker, name):
                setattr(module, name, getattr(broker, name))
        setattr(module, "_BROKER_MANAGER_AVAILABLE", all(hasattr(broker, n) for n in ("BrokerType", "KrakenBroker", "CoinbaseBroker", "BaseBroker")))
        setattr(module, "_BM_AVAILABLE", hasattr(broker, "BrokerManager"))

    mabm = _import_first("bot.multi_account_broker_manager", "multi_account_broker_manager")
    mabm_cls = getattr(mabm, "MultiAccountBrokerManager", None) if mabm else None
    setattr(module, "MultiAccountBrokerManager", mabm_cls)
    setattr(module, "_MABM_AVAILABLE", mabm_cls is not None)

    ibt = _import_first("bot.independent_broker_trader", "independent_broker_trader")
    ibt_cls = getattr(ibt, "IndependentBrokerTrader", None) if ibt else None
    setattr(module, "IndependentBrokerTrader", ibt_cls)
    setattr(module, "_IBT_AVAILABLE", ibt_cls is not None)

    core = _import_first("bot.nija_core_loop", "nija_core_loop")
    core_getter = getattr(core, "get_nija_core_loop", None) if core else None
    setattr(module, "get_nija_core_loop", core_getter)
    setattr(module, "_CORE_LOOP_AVAILABLE", callable(core_getter))

    pipeline = _import_first("bot.pipeline_order_submitter", "pipeline_order_submitter")
    submitter = getattr(pipeline, "submit_market_order_via_pipeline", None) if pipeline else None
    setattr(module, "submit_market_order_via_pipeline", submitter)

    market = _import_first("bot.market_readiness_gate", "market_readiness_gate")
    market_cls = getattr(market, "MarketReadinessGate", None) if market else None
    setattr(module, "MarketReadinessGate", market_cls)
    setattr(module, "_MARKET_READINESS_GATE_AVAILABLE", market_cls is not None)


def _patch_strategy_module(module: ModuleType) -> bool:
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False
    if getattr(cls, "_nija_v105_wrapped", False):
        return True

    original_init = cls.__init__

    @wraps(original_init)
    def _init(self: Any, *args: Any, **kwargs: Any) -> None:
        _hydrate_strategy_dependencies(module)
        return original_init(self, *args, **kwargs)

    cls.__init__ = _init  # type: ignore[assignment]
    setattr(cls, "_nija_v105_wrapped", True)
    LOGGER.critical(
        "CANONICAL_STRATEGY_PUBLICATION_V105_PATCHED marker=%s module=%s class_published=true lazy_dependency_hydration=true safety_gates_unchanged=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_mabm_module(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_on_platform_ready", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_v105_wrapped", False):
        return True

    @wraps(original)
    def _single_flight(self: Any, broker_type: Any) -> Any:
        if bool(getattr(self, "_nija_v105_platform_ready_inflight", False)):
            LOGGER.warning(
                "CAPITAL_PLATFORM_READY_V105_REENTRANT_SUPPRESSED marker=%s broker=%s real_snapshot_preserved=true trading_fail_closed=true",
                MARKER,
                getattr(broker_type, "value", str(broker_type)),
            )
            return None
        setattr(self, "_nija_v105_platform_ready_inflight", True)
        try:
            return original(self, broker_type)
        finally:
            setattr(self, "_nija_v105_platform_ready_inflight", False)

    setattr(_single_flight, "_nija_v105_wrapped", True)
    cls._on_platform_ready = _single_flight  # type: ignore[assignment]
    LOGGER.critical(
        "CAPITAL_PLATFORM_READY_V105_PATCHED marker=%s module=%s single_flight=true recursive_refresh_blocked=true snapshot_fabrication=false",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded_modules() -> None:
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and not _initializing(module):
            _patch_strategy_module(module)
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and not _initializing(module):
            _patch_mabm_module(module)


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            _patch_loaded_modules()
            return True

        current_import = builtins.__import__
        if not getattr(current_import, _HOOK_FLAG, False):
            setattr(builtins, _ORIGINAL_ATTR, current_import)

            @wraps(current_import)
            def _import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
                caller_initializing, caller = _caller_is_initializing(globals)
                absolute = str(name or "")
                if caller_initializing and level == 0 and absolute in _DEFERRED_IMPORTS:
                    LOGGER.warning(
                        "STARTUP_PUBLICATION_V105_DEFERRED marker=%s caller=%s dependency=%s reason=publish_canonical_class_first fail_closed=true",
                        MARKER,
                        caller,
                        absolute,
                    )
                    raise ImportError(f"v105 deferred optional import during TradingStrategy publication: {absolute}")

                result = current_import(name, globals, locals, fromlist, level)
                _patch_loaded_modules()
                return result

            setattr(_import, _HOOK_FLAG, True)
            setattr(_import, _ORIGINAL_ATTR, current_import)
            builtins.__import__ = _import

        _patch_loaded_modules()
        os.environ["NIJA_STARTUP_PUBLICATION_BOOTSTRAP_V105_INSTALLED"] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "STARTUP_PUBLICATION_BOOTSTRAP_V105_INSTALLED marker=%s class_first=true lazy_strategy_dependencies=true capital_callback_single_flight=true readiness_bypass=false position_fabrication=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
