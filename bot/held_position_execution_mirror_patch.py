from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Dict, Iterable, Tuple

logger = logging.getLogger("nija.held_position_execution_mirror")
_MARKER = "HELD_POSITION_EXECUTION_MIRROR_PATCHED marker=20260705h"
_PATCHED_ATTR = "_nija_held_position_execution_mirror_20260705h"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def _install_runtime_guard(module_name: str, marker: str) -> None:
    try:
        try:
            module = __import__(f"bot.{module_name}", fromlist=["*"])
        except Exception:
            module = __import__(module_name, fromlist=["*"])
        installer = getattr(module, "install_import_hook", None)
        if callable(installer):
            installer()
            logger.warning("%s marker=20260706a", marker)
    except Exception as exc:
        logger.warning("%s_FAILED marker=20260706a error=%s", marker, exc)


def _install_held_trade_cap_guard() -> None:
    os.environ.setdefault("NIJA_HELD_TRADE_CAP_GUARD_ENABLED", "true")
    os.environ.setdefault("NIJA_MAX_HELD_TRADES_PER_ACCOUNT", "8")
    _install_runtime_guard("held_trade_cap_guard_patch", "HELD_TRADE_CAP_GUARD_CHAINED_FROM_MIRROR")


def _install_global_trailing_protection() -> None:
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_PROTECTION_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_STOP_LOSS_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_TAKE_PROFIT_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_STOP_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_TAKE_PROFIT_ENABLED", "true")
    _install_runtime_guard("global_trailing_protection_patch", "GLOBAL_TRAILING_PROTECTION_CHAINED_FROM_MIRROR")


def _normalize_positions(raw_positions: Any) -> list[Dict[str, Any]]:
    if raw_positions is None:
        return []
    if isinstance(raw_positions, dict):
        out: list[Dict[str, Any]] = []
        for key, value in raw_positions.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("symbol", key)
                out.append(item)
        return out
    if isinstance(raw_positions, (list, tuple, set)):
        return [dict(p) for p in raw_positions if isinstance(p, dict)]
    return []


def _broker_name(raw: Any, broker: Any = None) -> str:
    text = str(getattr(raw, "value", raw) or "").strip().lower()
    if not text and broker is not None:
        for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
            value = getattr(broker, attr, None)
            raw_value = getattr(value, "value", value)
            text = str(raw_value or "").strip().lower()
            if text:
                break
    if not text and broker is not None:
        text = type(broker).__name__.replace("Broker", "").strip().lower()
    return text or "unknown"


def _collect_connected_brokers(strategy: Any, sync_module: ModuleType) -> Dict[str, Any]:
    collect = getattr(sync_module, "_collect_connected_brokers", None)
    if callable(collect):
        try:
            brokers = collect(strategy) or {}
            if brokers:
                return dict(brokers)
        except Exception as exc:
            logger.warning("HELD_POSITION_EXECUTION_MIRROR_COLLECT_SYNC_FAILED error=%s", exc)

    brokers: Dict[str, Any] = {}
    mam = getattr(strategy, "multi_account_manager", None)
    if mam is not None:
        try:
            for raw_key, broker in (getattr(mam, "platform_brokers", {}) or {}).items():
                if broker is not None and getattr(broker, "connected", False):
                    brokers[f"platform:{_broker_name(raw_key, broker)}"] = broker
        except Exception:
            pass
        try:
            for user_id, mapping in (getattr(mam, "user_brokers", {}) or {}).items():
                for raw_key, broker in (mapping or {}).items():
                    if broker is not None and getattr(broker, "connected", False):
                        brokers[f"user:{user_id}:{_broker_name(raw_key, broker)}"] = broker
        except Exception:
            pass
    bm = getattr(strategy, "broker_manager", None)
    if bm is not None:
        try:
            for raw_key, broker in (getattr(bm, "brokers", {}) or {}).items():
                if broker is not None and getattr(broker, "connected", False):
                    brokers.setdefault(f"broker_manager:{_broker_name(raw_key, broker)}", broker)
        except Exception:
            pass
    return brokers


def _read_positions_from_broker(broker_name: str, broker: Any) -> list[Dict[str, Any]]:
    tracker = getattr(broker, "position_tracker", None)
    if tracker is not None:
        try:
            positions = _normalize_positions(tracker.get_all_positions())
            if positions:
                return positions
        except Exception as exc:
            logger.debug("HELD_POSITION_EXECUTION_MIRROR tracker read skipped broker=%s error=%s", broker_name, exc)
    getter = getattr(broker, "get_positions", None)
    if callable(getter):
        try:
            return _normalize_positions(getter())
        except Exception as exc:
            logger.debug("HELD_POSITION_EXECUTION_MIRROR broker get_positions skipped broker=%s error=%s", broker_name, exc)
    return []


def _candidate_containers(strategy: Any) -> Iterable[Any]:
    seen: set[int] = set()

    def add(obj: Any):
        if obj is None:
            return
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)
        yield obj

    for obj in add(strategy) or []:
        yield obj
    for attr in ("apex", "core_loop", "nija_core_loop", "runtime", "owner", "parent", "trading_strategy"):
        try:
            for obj in add(getattr(strategy, attr, None)) or []:
                yield obj
        except Exception:
            pass
    try:
        try:
            from bot.nija_core_loop import get_nija_core_loop
        except ImportError:
            from nija_core_loop import get_nija_core_loop  # type: ignore
        core = get_nija_core_loop()
        for obj in add(core) or []:
            yield obj
    except Exception:
        pass


def _position_maps(strategy: Any) -> list[Tuple[str, Dict[str, Any]]]:
    maps: list[Tuple[str, Dict[str, Any]]] = []
    seen_maps: set[int] = set()
    for container in _candidate_containers(strategy):
        candidates = [("self", container)]
        for attr in ("execution_engine", "exit_engine", "trade_engine", "engine", "unified_execution_engine", "position_manager", "portfolio_manager"):
            try:
                candidates.append((attr, getattr(container, attr, None)))
            except Exception:
                pass
        for label, obj in candidates:
            if obj is None:
                continue
            pos_map = getattr(obj, "positions", None)
            if pos_map is None and _truthy("NIJA_HELD_POSITION_CREATE_POSITION_MAP", "true"):
                try:
                    setattr(obj, "positions", {})
                    pos_map = getattr(obj, "positions", None)
                except Exception:
                    pos_map = None
            if isinstance(pos_map, dict) and id(pos_map) not in seen_maps:
                seen_maps.add(id(pos_map))
                maps.append((f"{type(container).__name__}.{label}", pos_map))
    return maps


def _position_key(pos_map: Dict[str, Any], broker_name: str, symbol: str) -> str:
    if symbol not in pos_map:
        return symbol
    existing = pos_map.get(symbol)
    if isinstance(existing, dict):
        existing_broker = str(existing.get("broker_name") or existing.get("broker") or "").lower()
        if existing_broker == str(broker_name).lower():
            return symbol
    clean_broker = str(broker_name or "unknown").replace(":", "_")
    return f"{clean_broker}:{symbol}"


def _build_execution_position(pos: Dict[str, Any], broker_name: str, broker: Any) -> Dict[str, Any] | None:
    symbol = str(pos.get("symbol") or "").strip()
    if not symbol:
        return None
    qty = _float(pos.get("quantity", pos.get("qty", pos.get("amount", 0.0))), 0.0)
    entry = _float(pos.get("entry_price", pos.get("entry", pos.get("avg_entry_price", pos.get("current_price", 0.0)))), 0.0)
    current = _float(pos.get("current_price", pos.get("price", entry)), entry)
    size = _float(pos.get("size_usd", pos.get("value_usd", pos.get("market_value", 0.0))), 0.0)
    if size <= 0.0 and qty > 0.0 and (entry or current):
        size = qty * (entry or current)
    if qty <= 0.0 and size <= 0.0:
        return None
    if entry <= 0.0:
        entry = current
    stop_loss = _float(pos.get("stop_loss"), 0.0)
    if stop_loss <= 0.0 and entry > 0.0:
        stop_loss = entry * 0.97
    take_profit = pos.get("take_profit") or pos.get("take_profits")
    if not take_profit and entry > 0.0:
        take_profit = [entry * 1.01, entry * 1.018, entry * 1.026]
    broker_type = getattr(getattr(broker, "broker_type", None), "value", None) or _broker_name(broker_name, broker)
    return {
        "symbol": symbol,
        "side": str(pos.get("side", "long") or "long"),
        "entry_price": entry,
        "current_price": current,
        "quantity": qty,
        "size_usd": size,
        "position_size": size,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "entry_time": pos.get("entry_time") or pos.get("timestamp"),
        "strategy": pos.get("strategy", "STARTUP_SYNC"),
        "position_source": pos.get("position_source", "broker_existing"),
        "broker_name": broker_name,
        "broker": broker_type,
        "broker_type": broker_type,
        "broker_adapter": broker,
        "adopted_for_exit_management": True,
        "manage_existing_position_only": True,
        "held_position": True,
    }


def _mirror(strategy: Any, sync_module: ModuleType) -> int:
    brokers = _collect_connected_brokers(strategy, sync_module)
    maps = _position_maps(strategy)
    if not maps:
        logger.warning("HELD_POSITION_EXECUTION_MIRROR_NO_ENGINE_MAPS marker=20260705h brokers=%s", sorted(brokers.keys()))
        return 0
    mirrored = 0
    scanned = 0
    for broker_name, broker in brokers.items():
        for raw_pos in _read_positions_from_broker(broker_name, broker):
            scanned += 1
            built = _build_execution_position(raw_pos, broker_name, broker)
            if built is None:
                continue
            symbol = built["symbol"]
            for map_label, pos_map in maps:
                key = _position_key(pos_map, broker_name, symbol)
                existing = pos_map.get(key)
                if isinstance(existing, dict) and existing.get("adopted_for_exit_management"):
                    continue
                pos_map[key] = dict(built)
                pos_map[key]["execution_position_key"] = key
                mirrored += 1
                logger.critical(
                    "HELD_POSITION_EXECUTION_MIRRORED marker=20260705h engine=%s broker=%s key=%s symbol=%s qty=%.8f entry=$%.6f size=$%.2f",
                    map_label, broker_name, key, symbol,
                    _float(built.get("quantity"), 0.0), _float(built.get("entry_price"), 0.0), _float(built.get("size_usd"), 0.0),
                )
    logger.warning("HELD_POSITION_EXECUTION_MIRROR_COMPLETE marker=20260705h scanned=%d mirrored=%d maps=%d brokers=%d", scanned, mirrored, len(maps), len(brokers))
    return mirrored


def _patch_startup_sync(module: ModuleType) -> bool:
    original = getattr(module, "sync_exchange_positions_on_startup", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(callable(original))

    @wraps(original)
    def sync_exchange_positions_on_startup(strategy: Any) -> int:
        adopted = original(strategy)
        try:
            mirrored = _mirror(strategy, module)
        except Exception as exc:
            mirrored = 0
            logger.warning("HELD_POSITION_EXECUTION_MIRROR_FAILED marker=20260705h error=%s", exc)
        logger.warning("HELD_POSITION_EXIT_BRIDGE_RECHECK marker=20260705h adopted_total=%s mirrored_to_execution_engine=%d", adopted, mirrored)
        return adopted

    setattr(sync_exchange_positions_on_startup, _PATCHED_ATTR, True)
    setattr(module, "sync_exchange_positions_on_startup", sync_exchange_positions_on_startup)
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", module))
    print("[NIJA-PRINT] HELD_POSITION_EXECUTION_MIRROR_PATCHED marker=20260705h", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if name.endswith("startup_position_sync") and isinstance(module, ModuleType):
            patched = _patch_startup_sync(module) or patched
    return patched


def install_import_hook() -> None:
    _install_held_trade_cap_guard()
    _install_global_trailing_protection()
    if not _truthy("NIJA_HELD_POSITION_EXECUTION_MIRROR_ENABLED", "true"):
        logger.warning("HELD_POSITION_EXECUTION_MIRROR_DISABLED marker=20260705h")
        return
    os.environ.setdefault("NIJA_HELD_POSITION_EXECUTION_MIRROR_ENABLED", "true")
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_HELD_POSITION_EXECUTION_MIRROR_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("startup_position_sync"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("HELD_POSITION_EXECUTION_MIRROR hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_HELD_POSITION_EXECUTION_MIRROR_HOOK", True)
    logger.warning("HELD_POSITION_EXECUTION_MIRROR_IMPORT_HOOK marker=20260705h")


def install() -> None:
    install_import_hook()
