"""Runtime bridge for hard risk gates, explicit entry blockers, and held-position exits.

July 2026 live logs proved the scanner can select a signal and the TP geometry
repair now clears the ExecutionEngine target gate, but an ETH candidate continued
into execute_action after the portfolio sector engine had already emitted a hard
sector-limit block.  That produced a silent ``execute_entry returned None`` /
``execute_action returned False`` outcome instead of a deterministic pre-exec
veto.

This module keeps the hard risk limit intact and moves the decision to the last
safe boundary before execute_action.  It also mirrors startup-adopted exchange
holdings into the ExecutionEngine position map so Phase 2 can evaluate exits for
broker-existing positions after restart.
"""

from __future__ import annotations

import builtins
import logging
import os
from functools import wraps
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger("nija.risk_gate_execution_bridge")

_PATCHED_ATTR = "__nija_risk_gate_execution_bridge_patch__"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def _find_sector_engine(apex: Any) -> Optional[Any]:
    """Return the first object that exposes check_sector_limits()."""
    direct_names = (
        "portfolio_risk_engine",
        "portfolio_risk",
        "risk_engine",
        "correlation_risk_engine",
        "portfolio_intelligence",
    )
    for name in direct_names:
        obj = getattr(apex, name, None)
        if callable(getattr(obj, "check_sector_limits", None)):
            return obj

    ai_hub = getattr(apex, "ai_hub", None)
    if ai_hub is not None:
        for name in direct_names:
            obj = getattr(ai_hub, name, None)
            if callable(getattr(obj, "check_sector_limits", None)):
                return obj

    # Last-resort scan across apex/AI hub attributes.  This keeps the bridge
    # resilient to renamed composition fields without importing heavy modules.
    for container in (apex, ai_hub):
        if container is None:
            continue
        try:
            values = vars(container).values()
        except Exception:
            continue
        for obj in values:
            if callable(getattr(obj, "check_sector_limits", None)):
                return obj
    return None


def _enforce_sector_before_entry(apex: Any, symbol: str, analysis: Dict[str, Any], account_balance: float) -> Dict[str, Any]:
    action = str(analysis.get("action", "hold") or "hold")
    if action not in {"enter_long", "enter_short"}:
        return analysis

    size_usd = _as_float(analysis.get("position_size"), 0.0)
    portfolio_value = _as_float(account_balance, 0.0)
    if size_usd <= 0.0 or portfolio_value <= 0.0:
        return analysis

    sector_engine = _find_sector_engine(apex)
    if sector_engine is None:
        return analysis

    try:
        allowed, adjusted_size, info = sector_engine.check_sector_limits(symbol, size_usd, portfolio_value)
    except Exception as exc:
        logger.warning("SECTOR_RISK_PRE_EXECUTION_CHECK_ERROR symbol=%s error=%s", symbol, exc)
        return analysis

    info = dict(info or {})
    sector_name = info.get("sector_name") or info.get("sector") or "unknown"
    projected = _as_float(info.get("projected_sector_exposure_pct"), 0.0)
    hard = bool(info.get("hard_limit_triggered"))
    action_taken = str(info.get("enforcement_action", "none") or "none")

    if not allowed or hard or action_taken == "blocked":
        reason = (
            f"sector_risk_hard_limit:{symbol}:{sector_name}:"
            f"projected={projected * 100:.1f}%"
        )
        logger.critical(
            "SECTOR_RISK_PRE_EXECUTION_BLOCK symbol=%s sector=%s original_size=$%.2f "
            "projected_pct=%.1f action=%s reason=%s",
            symbol,
            sector_name,
            size_usd,
            projected * 100.0,
            action_taken,
            reason,
        )
        return {
            "action": "hold",
            "reason": reason,
            "filter_stage": "sector_risk_hard_limit",
            "sector_risk_info": info,
            "blocked_before_execute_action": True,
        }

    adjusted = _as_float(adjusted_size, size_usd)
    if adjusted > 0.0 and adjusted < size_usd:
        analysis["position_size"] = adjusted
        analysis["sector_risk_adjusted"] = True
        analysis["sector_risk_info"] = info
        logger.warning(
            "SECTOR_RISK_PRE_EXECUTION_SIZE_ADJUSTED symbol=%s sector=%s size=$%.2f->$%.2f projected_pct=%.1f",
            symbol,
            sector_name,
            size_usd,
            adjusted,
            projected * 100.0,
        )
    return analysis


def _patch_apex_strategy(module: Any) -> bool:
    patched = False
    for cls in list(vars(module).values()):
        if not isinstance(cls, type):
            continue
        if not callable(getattr(cls, "analyze_market", None)) or not callable(getattr(cls, "execute_action", None)):
            continue
        if getattr(cls, _PATCHED_ATTR, False):
            patched = True
            continue

        original_analyze = getattr(cls, "analyze_market")
        original_execute = getattr(cls, "execute_action")

        @wraps(original_analyze)
        def analyze_market(self: Any, df: Any, symbol: str, account_balance: float, *args: Any, __orig=original_analyze, **kwargs: Any) -> Dict[str, Any]:
            result = __orig(self, df, symbol, account_balance, *args, **kwargs)
            if not isinstance(result, dict):
                return result
            return _enforce_sector_before_entry(self, symbol, result, account_balance)

        @wraps(original_execute)
        def execute_action(self: Any, analysis: Dict[str, Any], symbol: str, *args: Any, __orig=original_execute, **kwargs: Any) -> Any:
            result = __orig(self, analysis, symbol, *args, **kwargs)
            if not result:
                try:
                    logger.critical(
                        "EXECUTE_ACTION_FALSE_BLOCKER symbol=%s action=%s filter_stage=%s reason=%s analysis_keys=%s",
                        symbol,
                        analysis.get("action") if isinstance(analysis, dict) else None,
                        analysis.get("filter_stage") if isinstance(analysis, dict) else None,
                        analysis.get("reason") if isinstance(analysis, dict) else None,
                        sorted(list(analysis.keys())) if isinstance(analysis, dict) else [],
                    )
                except Exception:
                    pass
            return result

        setattr(cls, "analyze_market", analyze_market)
        setattr(cls, "execute_action", execute_action)
        setattr(cls, _PATCHED_ATTR, True)
        patched = True
        logger.warning("RISK_GATE_EXECUTION_BRIDGE_APEX_PATCHED class=%s", getattr(cls, "__name__", cls))
    return patched


def _normalize_positions(raw_positions: Any) -> Iterable[Dict[str, Any]]:
    if raw_positions is None:
        return []
    if isinstance(raw_positions, dict):
        values = []
        for key, value in raw_positions.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("symbol", key)
                values.append(item)
        return values
    if isinstance(raw_positions, (list, tuple, set)):
        return [dict(p) for p in raw_positions if isinstance(p, dict)]
    return []


def _mirror_adopted_positions_to_execution_engine(strategy: Any, sync_module: Any) -> int:
    ee = getattr(strategy, "execution_engine", None)
    if ee is None or not isinstance(getattr(ee, "positions", None), dict):
        return 0

    collect = getattr(sync_module, "_collect_connected_brokers", None)
    if not callable(collect):
        return 0

    mirrored = 0
    try:
        brokers = collect(strategy) or {}
    except Exception as exc:
        logger.warning("HELD_POSITION_EXIT_BRIDGE_COLLECT_FAILED error=%s", exc)
        return 0

    for broker_name, broker in brokers.items():
        tracker = getattr(broker, "position_tracker", None)
        if tracker is None:
            continue
        try:
            raw_positions = tracker.get_all_positions()
        except Exception as exc:
            logger.debug("HELD_POSITION_EXIT_BRIDGE tracker read skipped broker=%s error=%s", broker_name, exc)
            continue
        for pos in _normalize_positions(raw_positions):
            symbol = str(pos.get("symbol", "") or "").strip()
            if not symbol or symbol in ee.positions:
                continue
            qty = _as_float(pos.get("quantity", pos.get("qty", 0.0)), 0.0)
            entry = _as_float(pos.get("entry_price", pos.get("entry", pos.get("current_price", 0.0))), 0.0)
            size = _as_float(pos.get("size_usd", pos.get("value_usd", 0.0)), 0.0)
            if size <= 0.0 and qty > 0.0 and entry > 0.0:
                size = qty * entry
            if qty <= 0.0 and size <= 0.0:
                continue
            stop_loss = _as_float(pos.get("stop_loss"), 0.0)
            if stop_loss <= 0.0 and entry > 0.0:
                stop_loss = entry * 0.97
            take_profit = pos.get("take_profit")
            if not take_profit and entry > 0.0:
                take_profit = [entry * 1.01, entry * 1.018, entry * 1.026]
            ee.positions[symbol] = {
                "symbol": symbol,
                "side": str(pos.get("side", "long") or "long"),
                "entry_price": entry,
                "quantity": qty,
                "size_usd": size,
                "position_size": size,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "entry_time": pos.get("entry_time"),
                "strategy": pos.get("strategy", "STARTUP_SYNC"),
                "position_source": pos.get("position_source", "broker_existing"),
                "broker_name": broker_name,
                "adopted_for_exit_management": True,
            }
            mirrored += 1
            logger.critical(
                "HELD_POSITION_EXIT_MANAGEMENT_MIRRORED broker=%s symbol=%s qty=%.8f entry=$%.6f size=$%.2f source=broker_existing",
                broker_name,
                symbol,
                qty,
                entry,
                size,
            )
    if mirrored:
        logger.warning("HELD_POSITION_EXIT_BRIDGE_SYNC mirrored=%d execution_engine_open=%d", mirrored, len(ee.positions))
    return mirrored


def _patch_startup_position_sync(module: Any) -> bool:
    original = getattr(module, "sync_exchange_positions_on_startup", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(callable(original))

    @wraps(original)
    def sync_exchange_positions_on_startup(strategy: Any) -> int:
        adopted = original(strategy)
        mirrored = _mirror_adopted_positions_to_execution_engine(strategy, module)
        logger.warning(
            "HELD_POSITION_EXIT_BRIDGE_COMPLETE adopted_total=%s mirrored_to_execution_engine=%d",
            adopted,
            mirrored,
        )
        return adopted

    setattr(sync_exchange_positions_on_startup, _PATCHED_ATTR, True)
    setattr(module, "sync_exchange_positions_on_startup", sync_exchange_positions_on_startup)
    logger.warning("HELD_POSITION_EXIT_BRIDGE_PATCHED module=%s", getattr(module, "__name__", module))
    return True


def _patch_module(name: str, module: Any) -> None:
    if module is None:
        return
    try:
        if name.endswith("nija_apex_strategy_v71") or name.endswith("apex_strategy"):
            _patch_apex_strategy(module)
        if name.endswith("startup_position_sync"):
            _patch_startup_position_sync(module)
    except Exception as exc:
        logger.warning("Risk gate execution bridge patch failed for %s: %s", name, exc)


def install_import_hook() -> None:
    if not _truthy("NIJA_RISK_GATE_EXECUTION_BRIDGE_ENABLED", True):
        logger.warning("RISK_GATE_EXECUTION_BRIDGE_DISABLED")
        return

    import sys

    os.environ.setdefault("NIJA_RISK_GATE_EXECUTION_BRIDGE_ENABLED", "true")
    for name, module in list(sys.modules.items()):
        if name.endswith(("nija_apex_strategy_v71", "startup_position_sync")):
            _patch_module(name, module)

    if getattr(builtins, "_NIJA_RISK_GATE_EXECUTION_BRIDGE_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            targets = ("nija_apex_strategy_v71", "startup_position_sync")
            if name.endswith(targets):
                _patch_module(name, module)
            for loaded_name, loaded_module in list(sys.modules.items()):
                if loaded_name.endswith(targets):
                    _patch_module(loaded_name, loaded_module)
        except Exception as exc:
            logger.warning("Risk gate execution bridge import hook failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_RISK_GATE_EXECUTION_BRIDGE_INSTALLED", True)
    logger.warning("RISK_GATE_EXECUTION_BRIDGE_INSTALL_COMPLETE")
