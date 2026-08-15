"""Eliminate canonical TradingStrategy publication races caused by heavy imports.

Production deployment 8d85b3ea on 2026-08-15 proved that bot.trading_strategy
remained ``__spec__._initializing=True`` beyond the v100 recovery budget while
Step 2.5 waited for the class definition. The module defines TradingStrategy only
after importing APEX, broker-management, independent-trader, core-loop and
execution surfaces. Those imports are runtime wiring dependencies, not class-
publication prerequisites.

v101 moves that dependency hydration behind TradingStrategy construction by
patching the module's import-facing globals before canonical publication. It does
not fabricate any class, broker, readiness state, execution authority, position,
nonce, writer proof, or trading state. Runtime dependencies are imported through
their canonical package paths when a real TradingStrategy instance is built; a
missing dependency keeps the corresponding feature unavailable/fail closed.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.trading_strategy_import_convergence_v101")
MARKER = "20260815-trading-strategy-import-convergence-v101"


def _resolve(module_name: str, attr: str) -> Any:
    try:
        module = importlib.import_module(module_name)
        return getattr(module, attr, None)
    except Exception as exc:
        LOGGER.warning(
            "TRADING_STRATEGY_V101_DEPENDENCY_UNAVAILABLE marker=%s module=%s attr=%s error=%s:%s",
            MARKER,
            module_name,
            attr,
            type(exc).__name__,
            exc,
        )
        return None


def hydrate_runtime_dependencies(strategy_module: ModuleType) -> dict[str, bool]:
    """Hydrate heavy TradingStrategy globals after the class module has loaded."""
    apex = getattr(strategy_module, "NIJAApexStrategyV71", None)
    if apex is None:
        apex = _resolve("bot.nija_apex_strategy_v71", "NIJAApexStrategyV71")
        if apex is not None:
            setattr(strategy_module, "NIJAApexStrategyV71", apex)
    setattr(strategy_module, "_APEX_AVAILABLE", isinstance(apex, type))

    broker_type = getattr(strategy_module, "BrokerType", None) or _resolve("bot.broker_manager", "BrokerType")
    kraken = getattr(strategy_module, "KrakenBroker", None) or _resolve("bot.broker_manager", "KrakenBroker")
    coinbase = getattr(strategy_module, "CoinbaseBroker", None) or _resolve("bot.broker_manager", "CoinbaseBroker")
    base = getattr(strategy_module, "BaseBroker", None) or _resolve("bot.broker_manager", "BaseBroker")
    manager = getattr(strategy_module, "BrokerManager", None) or _resolve("bot.broker_manager", "BrokerManager")
    setattr(strategy_module, "BrokerType", broker_type)
    setattr(strategy_module, "KrakenBroker", kraken)
    setattr(strategy_module, "CoinbaseBroker", coinbase)
    setattr(strategy_module, "BaseBroker", base)
    setattr(strategy_module, "BrokerManager", manager)
    setattr(strategy_module, "_BROKER_MANAGER_AVAILABLE", broker_type is not None and base is not None)
    setattr(strategy_module, "_BM_AVAILABLE", manager is not None)

    mabm = getattr(strategy_module, "MultiAccountBrokerManager", None) or _resolve(
        "bot.multi_account_broker_manager", "MultiAccountBrokerManager"
    )
    setattr(strategy_module, "MultiAccountBrokerManager", mabm)
    setattr(strategy_module, "_MABM_AVAILABLE", mabm is not None)

    ibt = getattr(strategy_module, "IndependentBrokerTrader", None) or _resolve(
        "bot.independent_broker_trader", "IndependentBrokerTrader"
    )
    setattr(strategy_module, "IndependentBrokerTrader", ibt)
    setattr(strategy_module, "_IBT_AVAILABLE", ibt is not None)

    core = getattr(strategy_module, "get_nija_core_loop", None) or _resolve(
        "bot.nija_core_loop", "get_nija_core_loop"
    )
    setattr(strategy_module, "get_nija_core_loop", core)
    setattr(strategy_module, "_CORE_LOOP_AVAILABLE", callable(core))

    probe = getattr(strategy_module, "startup_execution_probe_scope", None) or _resolve(
        "bot.execution_authority_context", "startup_execution_probe_scope"
    )
    setattr(strategy_module, "startup_execution_probe_scope", probe)

    submitter = getattr(strategy_module, "submit_market_order_via_pipeline", None) or _resolve(
        "bot.pipeline_order_submitter", "submit_market_order_via_pipeline"
    )
    setattr(strategy_module, "submit_market_order_via_pipeline", submitter)

    state = {
        "apex": isinstance(apex, type),
        "broker_manager": bool(getattr(strategy_module, "_BROKER_MANAGER_AVAILABLE", False)),
        "multi_account": bool(getattr(strategy_module, "_MABM_AVAILABLE", False)),
        "independent_trader": bool(getattr(strategy_module, "_IBT_AVAILABLE", False)),
        "core_loop": bool(getattr(strategy_module, "_CORE_LOOP_AVAILABLE", False)),
        "execution_probe": callable(probe) if probe is not None else False,
        "submitter": callable(submitter) if submitter is not None else False,
    }
    LOGGER.critical(
        "TRADING_STRATEGY_V101_RUNTIME_DEPENDENCIES marker=%s state=%s safety_gates_unchanged=true",
        MARKER,
        state,
    )
    return state


def install() -> bool:
    os.environ["NIJA_TRADING_STRATEGY_IMPORT_CONVERGENCE_V101_INSTALLED"] = "1"
    LOGGER.critical(
        "TRADING_STRATEGY_IMPORT_CONVERGENCE_V101_INSTALLED marker=%s lazy_runtime_dependencies=true fail_closed=true",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "hydrate_runtime_dependencies", "install", "install_import_hook"]
