"""Broker-native profit and loss exit supervisor for every NIJA account.

This guard does not depend on one ExecutionEngine owning or mirroring a position.
Every connected Kraken, Coinbase and OKX broker instance is registered directly,
and its native position tracker is scanned for platform and user holdings.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
import weakref
from functools import wraps
from typing import Any

from bot import auto_exit_sl_tp_runtime_patch as auto_exit

logger = logging.getLogger("nija.universal_broker_exit_supervisor")
_MARKER = "20260716-universal-exit-v1"
_PATCHED = "__nija_universal_broker_exit_supervisor_v1__"
_LOCK = threading.RLock()
_BROKERS: "weakref.WeakSet[Any]" = weakref.WeakSet()
_STRONG_BROKERS: list[Any] = []
_ACTIVE: set[str] = set()
_STARTED = False


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _account_label(broker: Any) -> str:
    for name in ("account_id", "account_name", "user_id", "username", "label", "name"):
        value = getattr(broker, name, None)
        if value:
            return str(value)
    return "platform"


def _tracker_positions(broker: Any) -> list[dict[str, Any]]:
    tracker = getattr(broker, "position_tracker", None)
    candidates: list[Any] = []
    if tracker is not None:
        for method_name in ("get_all_positions", "get_open_positions", "list_positions"):
            method = getattr(tracker, method_name, None)
            if callable(method):
                try:
                    raw = method()
                    if isinstance(raw, dict):
                        candidates.extend(dict(value, symbol=value.get("symbol") or key) for key, value in raw.items() if isinstance(value, dict))
                    elif isinstance(raw, (list, tuple, set)):
                        candidates.extend(raw)
                    if candidates:
                        break
                except Exception:
                    continue
    for attr in ("positions", "open_positions", "tracked_positions"):
        raw = getattr(broker, attr, None)
        if isinstance(raw, dict):
            candidates.extend(dict(value, symbol=value.get("symbol") or key) for key, value in raw.items() if isinstance(value, dict))
        elif isinstance(raw, (list, tuple, set)):
            candidates.extend(raw)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in candidates:
        pos = raw if isinstance(raw, dict) else dict(getattr(raw, "__dict__", {}) or {})
        symbol = auto_exit._sym(pos.get("symbol"))
        qty = auto_exit._quantity(pos)
        if not symbol or qty <= 0:
            continue
        key = f"{symbol}:{pos.get('position_id') or ''}:{qty:.12f}"
        if key in seen:
            continue
        seen.add(key)
        pos = dict(pos)
        pos["symbol"] = symbol
        pos.setdefault("account_id", _account_label(broker))
        normalized.append(pos)
    return normalized


def _fee_aware_profit_target(broker: Any, pos: dict[str, Any]) -> float:
    entry = auto_exit._entry_price(pos)
    if entry <= 0:
        return 0.0
    explicit = max(
        _f(pos.get("take_profit")),
        _f(pos.get("take_profit_1")),
        _f(pos.get("profit_target")),
    )
    if explicit > 0:
        return explicit
    label = auto_exit._broker_label(broker)
    venue_default = 0.014
    if "kraken" in label:
        venue_default = 0.008
    elif "okx" in label:
        venue_default = 0.004
    round_trip = max(0.0, _f(os.environ.get(f"NIJA_{label.upper()}_ROUND_TRIP_FEE_PCT"), _f(os.environ.get("NIJA_EXIT_ROUND_TRIP_FEE_PCT"), venue_default)))
    slippage = max(0.0, _f(os.environ.get("NIJA_EXIT_SLIPPAGE_RESERVE_PCT"), 0.0015))
    minimum_net = max(0.0, _f(os.environ.get("NIJA_MINIMUM_NET_PROFIT_PCT"), 0.004))
    return entry * (1.0 + round_trip + slippage + minimum_net)


def _trigger(broker: Any, pos: dict[str, Any], market: float) -> tuple[bool, str, float]:
    hit, reason, target = auto_exit._trigger(pos, market)
    if hit:
        return hit, reason, target
    side = auto_exit._side(pos.get("side"), pos)
    profit_target = _fee_aware_profit_target(broker, pos)
    if profit_target > 0:
        if side in {"long", "buy"} and market >= profit_target:
            return True, "fee_aware_net_profit_target", profit_target
        if side in {"short", "sell"} and market <= profit_target:
            return True, "fee_aware_net_profit_target", profit_target
    return False, "", 0.0


def _mark_closed(broker: Any, pos: dict[str, Any], order: dict[str, Any], reason: str, market: float) -> None:
    tracker = getattr(broker, "position_tracker", None)
    symbol = auto_exit._sym(pos.get("symbol"))
    pid = str(pos.get("position_id") or symbol)
    fill = _f(auto_exit._get(order, "filled_price", "average_fill_price", "avg_price", "price", default=market), market)
    fee = _f(auto_exit._get(order, "fee", "commission", "fees", default=0.0))
    order_id = str(auto_exit._get(order, "order_id", "id", "txid", "client_order_id", default="") or "")
    for owner in (tracker, broker):
        if owner is None:
            continue
        for name in ("close_position_with_pnl", "close_position", "mark_position_closed", "remove_position"):
            method = getattr(owner, name, None)
            if not callable(method):
                continue
            attempts = (
                {"position_id": pid, "symbol": symbol, "exit_price": fill, "exit_fee": fee, "exit_reason": reason, "order_id": order_id, "broker": auto_exit._broker_label(broker)},
                {"symbol": symbol, "exit_price": fill, "reason": reason},
                {"symbol": symbol},
            )
            for kwargs in attempts:
                try:
                    method(**kwargs)
                    return
                except TypeError:
                    continue
                except Exception:
                    break


def _scan_broker(broker: Any) -> int:
    closed = 0
    account = _account_label(broker)
    venue = auto_exit._broker_label(broker)
    for pos in _tracker_positions(broker):
        symbol = auto_exit._sym(pos.get("symbol"))
        pid = str(pos.get("position_id") or symbol)
        key = f"{id(broker)}:{pid}:{symbol}"
        if key in _ACTIVE:
            continue
        entry = auto_exit._entry_price(pos)
        qty = auto_exit._quantity(pos)
        if entry <= 0 or qty <= 0:
            logger.warning("UNIVERSAL_EXIT_SKIPPED_UNVERIFIED_POSITION marker=%s venue=%s account=%s symbol=%s entry=%.8f qty=%.8f", _MARKER, venue, account, symbol, entry, qty)
            continue
        market = auto_exit._price(broker, symbol)
        if market <= 0:
            logger.warning("UNIVERSAL_EXIT_PRICE_UNAVAILABLE marker=%s venue=%s account=%s symbol=%s", _MARKER, venue, account, symbol)
            continue
        hit, reason, target = _trigger(broker, pos, market)
        side = auto_exit._side(pos.get("side"), pos)
        unrealized = (market - entry) * qty if side in {"long", "buy"} else (entry - market) * qty
        if not hit:
            continue
        _ACTIVE.add(key)
        logger.critical(
            "UNIVERSAL_BROKER_EXIT_TRIGGER marker=%s venue=%s account=%s symbol=%s reason=%s target=%.8f market=%.8f entry=%.8f qty=%.8f unrealized=$%+.2f",
            _MARKER, venue, account, symbol, reason, target, market, entry, qty, unrealized,
        )
        order = auto_exit._exit_order(broker, pos, market)
        if not auto_exit._ok(order):
            logger.error("UNIVERSAL_BROKER_EXIT_FAILED marker=%s venue=%s account=%s symbol=%s reason=%s error=%s", _MARKER, venue, account, symbol, reason, order)
            _ACTIVE.discard(key)
            continue
        _mark_closed(broker, pos, order, reason, market)
        closed += 1
        auto_exit._HIGH_WATER.pop(auto_exit._position_key(pos), None)
        logger.critical("UNIVERSAL_BROKER_EXIT_CONFIRMED marker=%s venue=%s account=%s symbol=%s reason=%s order_id=%s", _MARKER, venue, account, symbol, reason, auto_exit._get(order, "order_id", "id", "txid", default=""))
        _ACTIVE.discard(key)
    return closed


def _register_broker(broker: Any) -> None:
    if broker is None:
        return
    with _LOCK:
        try:
            _BROKERS.add(broker)
        except TypeError:
            if broker not in _STRONG_BROKERS:
                _STRONG_BROKERS.append(broker)
    logger.info("UNIVERSAL_BROKER_EXIT_REGISTERED marker=%s venue=%s account=%s class=%s", _MARKER, auto_exit._broker_label(broker), _account_label(broker), type(broker).__name__)
    _start()


def _snapshot() -> list[Any]:
    values = list(_BROKERS) + list(_STRONG_BROKERS)
    out: list[Any] = []
    seen: set[int] = set()
    for broker in values:
        if broker is not None and id(broker) not in seen:
            seen.add(id(broker))
            out.append(broker)
    return out


def _start() -> None:
    global _STARTED
    if not _truthy("NIJA_UNIVERSAL_BROKER_EXIT_ENABLED", "true"):
        return
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    interval = max(1.0, _f(os.environ.get("NIJA_UNIVERSAL_EXIT_POLL_SECONDS"), 3.0))

    def loop() -> None:
        logger.critical("UNIVERSAL_BROKER_EXIT_SUPERVISOR_STARTED marker=%s interval_s=%.2f platform_and_users=true venues=kraken,coinbase,okx", _MARKER, interval)
        while _truthy("NIJA_UNIVERSAL_BROKER_EXIT_ENABLED", "true"):
            for broker in _snapshot():
                try:
                    _scan_broker(broker)
                except Exception as exc:
                    logger.exception("UNIVERSAL_BROKER_EXIT_SCAN_FAILED marker=%s class=%s err=%s", _MARKER, type(broker).__name__, exc)
            time.sleep(interval)

    threading.Thread(target=loop, name="UniversalBrokerExitSupervisor", daemon=True).start()


def _patch_module(module: Any) -> bool:
    patched = False
    for class_name in (
        "KrakenBroker", "KrakenBrokerAdapter", "CoinbaseBroker", "CoinbaseBrokerAdapter",
        "_CoinbaseInvalidProductFilter", "OKXBroker", "OKXBrokerAdapter",
    ):
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type) or getattr(cls, _PATCHED, False):
            continue
        original_init = getattr(cls, "__init__", None)
        if callable(original_init):
            @wraps(original_init)
            def init(self: Any, *args: Any, __orig=original_init, **kwargs: Any):
                __orig(self, *args, **kwargs)
                _register_broker(self)
            cls.__init__ = init
        original_connect = getattr(cls, "connect", None)
        if callable(original_connect):
            @wraps(original_connect)
            def connect(self: Any, *args: Any, __orig=original_connect, **kwargs: Any):
                result = __orig(self, *args, **kwargs)
                _register_broker(self)
                return result
            cls.connect = connect
        setattr(cls, _PATCHED, True)
        patched = True
        logger.warning("UNIVERSAL_BROKER_EXIT_CLASS_PATCHED marker=%s class=%s", _MARKER, class_name)
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_UNIVERSAL_BROKER_EXIT_ENABLED", "true")
    os.environ.setdefault("NIJA_UNIVERSAL_EXIT_POLL_SECONDS", "3")
    os.environ.setdefault("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true")
    os.environ.setdefault("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    os.environ.setdefault("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    auto_exit.install_import_hook()
    for module in list(sys.modules.values()):
        if module is not None:
            _patch_module(module)
    _start()
    if getattr(builtins, "_NIJA_UNIVERSAL_BROKER_EXIT_IMPORT_HOOK_V1", False):
        os.environ["NIJA_UNIVERSAL_BROKER_EXIT_SUPERVISOR_INSTALLED"] = "1"
        return
    original_import = builtins.__import__

    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            _patch_module(module)
            for loaded in list(sys.modules.values()):
                if loaded is not None:
                    _patch_module(loaded)
        except Exception as exc:
            logger.warning("UNIVERSAL_BROKER_EXIT_IMPORT_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = hook
    setattr(builtins, "_NIJA_UNIVERSAL_BROKER_EXIT_IMPORT_HOOK_V1", True)
    os.environ["NIJA_UNIVERSAL_BROKER_EXIT_SUPERVISOR_INSTALLED"] = "1"
    logger.critical("UNIVERSAL_BROKER_EXIT_SUPERVISOR_INSTALLED marker=%s broker_native=true platform_and_users=true", _MARKER)


def install() -> None:
    install_import_hook()
