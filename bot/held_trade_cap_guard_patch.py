from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger("nija.held_trade_cap_guard")
_MARKER = "HELD_TRADE_CAP_GUARD_PATCHED marker=20260706a"
_PATCHED_ATTR = "_nija_held_trade_cap_guard_20260706a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_CASH_ASSETS = {"USD", "USDT", "USDC", "DAI", "EUR", "GBP", "ZUSD", "USDG"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _cap() -> int:
    try:
        return max(1, int(float(os.environ.get("NIJA_MAX_HELD_TRADES_PER_ACCOUNT", "8"))))
    except Exception:
        return 8


def _norm_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    for key in ("coinbase", "kraken", "okx", "alpaca", "binance"):
        if key in text:
            return key
    return text or "unknown"


def _broker_name(broker: Any, fallback: str = "unknown") -> str:
    if broker is None:
        return fallback
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name", "venue"):
        try:
            name = _norm_name(getattr(broker, attr, None))
            if name and name != "unknown":
                return name
        except Exception:
            pass
    return _norm_name(type(broker).__name__) or fallback


def _account_id(broker: Any, fallback: str = "platform") -> str:
    for attr in ("account_id", "user_id", "account_name", "label", "owner"):
        try:
            val = getattr(broker, attr, None)
            if val:
                return str(val)
        except Exception:
            pass
    return fallback


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    data = getattr(value, "__dict__", None)
    if isinstance(data, Mapping):
        return data
    return None


def _symbol(pos: Any, fallback: str = "") -> str:
    mp = _mapping(pos)
    if mp:
        raw = mp.get("symbol") or mp.get("pair") or mp.get("market") or mp.get("product_id") or mp.get("asset") or mp.get("currency") or fallback
    else:
        raw = getattr(pos, "symbol", None) or getattr(pos, "pair", None) or getattr(pos, "market", None) or getattr(pos, "product_id", None) or getattr(pos, "asset", None) or fallback
    return str(raw or "").strip().upper()


def _qty(pos: Any) -> float:
    keys = ("qty", "quantity", "amount", "size", "units", "balance", "total", "available", "free", "base_size")
    mp = _mapping(pos)
    for key in keys:
        try:
            val = mp.get(key) if mp else getattr(pos, key, None)
            if val is not None and str(val).strip() != "":
                out = abs(float(str(val).replace(",", "")))
                if out > 0:
                    return out
        except Exception:
            pass
    return 0.0


def _open_status(pos: Any) -> bool:
    mp = _mapping(pos)
    try:
        status = str((mp.get("status") if mp else getattr(pos, "status", "")) or "").strip().lower()
    except Exception:
        status = ""
    return status not in {"closed", "done", "cancelled", "canceled", "expired", "rejected", "failed", "error", "settled"}


def _positions(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("positions", "open_positions", "holdings", "assets", "balances", "data", "result"):
            val = payload.get(key)
            if isinstance(val, Sequence) and not isinstance(val, (str, bytes, bytearray)):
                return list(val)
            if isinstance(val, Mapping):
                return _positions(val)
        out: list[Any] = []
        for key, val in payload.items():
            if isinstance(val, Mapping):
                item = dict(val)
                item.setdefault("symbol", key)
                item.setdefault("asset", key)
                out.append(item)
            else:
                try:
                    qty = abs(float(str(val).replace(",", "")))
                    if qty > 0:
                        out.append({"symbol": key, "asset": key, "qty": qty, "status": "open"})
                except Exception:
                    pass
        return out
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return list(payload)
    return []


def _position_payloads(obj: Any) -> Iterable[Any]:
    if obj is None:
        return []
    out: list[Any] = []
    for attr in (
        "open_positions", "positions", "_open_positions", "_positions", "tracked_positions", "_tracked_positions",
        "cached_positions", "_cached_positions", "balance_cache", "_balance_cache", "raw_balances", "_raw_balances",
    ):
        try:
            out.extend(_positions(getattr(obj, attr, None)))
        except Exception:
            pass
    for method_name in ("get_open_positions", "get_positions", "get_spot_positions", "get_spot_holdings", "get_holdings"):
        fn = getattr(obj, method_name, None)
        if callable(fn):
            try:
                out.extend(_positions(fn()))
            except Exception:
                pass
    return out


def _held_count(obj: Any) -> int:
    seen: set[str] = set()
    for pos in _position_payloads(obj):
        sym = _symbol(pos)
        if not sym or not _open_status(pos):
            continue
        base = sym.replace("/", "-").replace("_", "-").split("-", 1)[0].upper()
        if base in _CASH_ASSETS:
            continue
        if _qty(pos) <= 0 and not sym:
            continue
        seen.add(sym)
    return len(seen)


def _candidate_objects(core_loop: Any, broker: Any) -> list[Any]:
    out: list[Any] = []
    for obj in (broker, core_loop, getattr(core_loop, "apex", None)):
        if obj is not None:
            out.append(obj)
            for attr in ("broker", "broker_client", "active_broker", "position_tracker", "trade_ledger", "ledger"):
                try:
                    val = getattr(obj, attr, None)
                    if val is not None:
                        out.append(val)
                except Exception:
                    pass
            for attr in ("brokers", "platform_brokers", "user_brokers", "GLOBAL_PLATFORM_BROKERS", "_PLATFORM_BROKER_INSTANCES"):
                try:
                    val = getattr(obj, attr, None)
                    if isinstance(val, Mapping):
                        out.extend(list(val.values()))
                except Exception:
                    pass
    return out


def _best_count(core_loop: Any, broker: Any, fallback: int) -> tuple[int, str, str]:
    best = max(0, int(fallback or 0))
    best_broker = _broker_name(broker)
    best_account = _account_id(broker)
    seen_ids: set[int] = set()
    for obj in _candidate_objects(core_loop, broker):
        oid = id(obj)
        if oid in seen_ids:
            continue
        seen_ids.add(oid)
        count = _held_count(obj)
        if count > best:
            best = count
            best_broker = _broker_name(obj, best_broker)
            best_account = _account_id(obj, best_account)
    return best, best_broker, best_account


def _result_like(module: ModuleType, **updates: Any) -> Any:
    cls = getattr(module, "CoreLoopResult", None)
    result = cls() if callable(cls) else type("HeldTradeCapResult", (), {})()
    for key, value in updates.items():
        try:
            setattr(result, key, value)
        except Exception:
            pass
    return result


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "run_scan_phase", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def run_scan_phase(self: Any, broker: Any, balance: float, symbols: list[str], open_positions_count: int = 0, user_mode: bool = False):
        if not _truthy("NIJA_HELD_TRADE_CAP_GUARD_ENABLED", "true"):
            return original(self, broker, balance, symbols, open_positions_count, user_mode)
        cap = _cap()
        held, broker_name, account = _best_count(self, broker, open_positions_count)
        if held >= cap:
            logger.critical(
                "HELD_TRADE_CAP_BLOCKED marker=20260706a broker=%s account_id=%s held=%d cap=%d action=skip_new_entries exits_still_allowed=true",
                broker_name,
                account,
                held,
                cap,
            )
            print(
                f"[NIJA-PRINT] HELD_TRADE_CAP_BLOCKED marker=20260706a broker={broker_name} account_id={account} held={held} cap={cap}",
                flush=True,
            )
            return _result_like(module, entries_taken=0, entries_blocked=1, symbols_scored=0, exits_taken=0, errors=[f"held_trade_cap:{held}/{cap}"], next_interval=150)
        return original(self, broker, balance, symbols, open_positions_count, user_mode)

    setattr(run_scan_phase, _PATCHED_ATTR, True)
    setattr(cls, "run_scan_phase", run_scan_phase)
    logger.warning("%s class=NijaCoreLoop cap=%d", _MARKER, _cap())
    print(f"[NIJA-PRINT] HELD_TRADE_CAP_GUARD_PATCHED marker=20260706a cap={_cap()}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_HELD_TRADE_CAP_GUARD_ENABLED", "true")
    os.environ.setdefault("NIJA_MAX_HELD_TRADES_PER_ACCOUNT", "8")
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_HELD_TRADE_CAP_GUARD_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("nija_core_loop"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("HELD_TRADE_CAP_GUARD hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_HELD_TRADE_CAP_GUARD_HOOK", True)
    logger.warning("HELD_TRADE_CAP_GUARD_IMPORT_HOOK marker=20260706a cap=%d", _cap())


def install() -> None:
    install_import_hook()
