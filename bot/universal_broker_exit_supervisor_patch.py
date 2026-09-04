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
_MARKER = "20260802-universal-exit-shared-state-v2"
_OPERATOR_MARKER = "20260831-operator-net-profit-exit-v1"
_PATCHED = "__nija_universal_broker_exit_supervisor_v1__"
_STATE_KEY = "_NIJA_UNIVERSAL_BROKER_EXIT_SHARED_STATE_V2"
if not hasattr(builtins, _STATE_KEY):
    setattr(
        builtins,
        _STATE_KEY,
        {
            "lock": threading.RLock(),
            "brokers": weakref.WeakSet(),
            "strong_brokers": [],
            "active": set(),
            "duplicate_accounts": set(),
            "started": False,
        },
    )
_STATE: dict[str, Any] = getattr(builtins, _STATE_KEY)
_LOCK: threading.RLock = _STATE["lock"]
_BROKERS: "weakref.WeakSet[Any]" = _STATE["brokers"]
_STRONG_BROKERS: list[Any] = _STATE["strong_brokers"]
_ACTIVE: set[str] = _STATE["active"]
_DUPLICATE_ACCOUNTS: set[tuple[str, str]] = _STATE["duplicate_accounts"]
_STARTED = bool(_STATE["started"])


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


def _venue_cost_pct(broker: Any) -> float:
    label = auto_exit._broker_label(broker)
    venue_default = 0.014
    if "kraken" in label:
        venue_default = 0.008
    elif "okx" in label:
        venue_default = 0.004
    round_trip = max(
        0.0,
        _f(
            os.environ.get(f"NIJA_{label.upper()}_ROUND_TRIP_FEE_PCT"),
            _f(os.environ.get("NIJA_EXIT_ROUND_TRIP_FEE_PCT"), venue_default),
        ),
    )
    slippage = max(0.0, _f(os.environ.get("NIJA_EXIT_SLIPPAGE_RESERVE_PCT"), 0.0015))
    return round_trip + slippage


def _operator_profit_exit_active() -> bool:
    if not _truthy("NIJA_OPERATOR_NET_PROFIT_EXIT_ENABLED", "false"):
        return False
    until_epoch = _f(os.environ.get("NIJA_OPERATOR_NET_PROFIT_EXIT_UNTIL_EPOCH"), 0.0)
    return bool(until_epoch > 0.0 and time.time() <= until_epoch)


def _operator_basis_verified(pos: dict[str, Any]) -> bool:
    if auto_exit._entry_price(pos) <= 0 or auto_exit._quantity(pos) <= 0:
        return False
    if pos.get("cost_basis_verified") is False:
        return False
    if bool(pos.get("auto_exit_blocked", False)):
        return False
    return True


def _operator_net_profit_target(broker: Any, pos: dict[str, Any]) -> float:
    if not _operator_basis_verified(pos):
        return 0.0
    entry = auto_exit._entry_price(pos)
    minimum_net = max(0.0, _f(os.environ.get("NIJA_OPERATOR_MIN_NET_PROFIT_PCT"), 0.0005))
    return entry * (1.0 + _venue_cost_pct(broker) + minimum_net)


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
    minimum_net = max(0.0, _f(os.environ.get("NIJA_MINIMUM_NET_PROFIT_PCT"), 0.004))
    return entry * (1.0 + _venue_cost_pct(broker) + minimum_net)


def _account_recovery_snapshot(broker: Any) -> dict[str, Any]:
    try:
        module = importlib.import_module("bot.broker_account_isolation_v64_patch")
        getter = getattr(module, "get_account_recovery_snapshot", None)
        if callable(getter):
            return dict(getter(broker) or {})
    except Exception as exc:
        logger.debug("RECOVERY_EXIT_STATE_UNAVAILABLE broker=%s error=%s", auto_exit._broker_label(broker), exc)
    return {}


def _recovery_position_trigger(
    broker: Any,
    pos: dict[str, Any],
    market: float,
) -> tuple[bool, str, float]:
    """Tighten held-position protection during account drawdown.

    This never changes quantity, adds exposure, raises leverage, averages down,
    or widens a stop.  Profit exits remain fee/slippage positive.
    """
    snapshot = _account_recovery_snapshot(broker)
    if not bool(snapshot.get("in_recovery", False)):
        return False, "", 0.0
    if not _operator_basis_verified(pos):
        return False, "", 0.0

    entry = auto_exit._entry_price(pos)
    side = auto_exit._side(pos.get("side"), pos)
    if entry <= 0.0 or market <= 0.0:
        return False, "", 0.0

    max_loss = max(0.001, min(0.05, _f(os.environ.get("NIJA_RECOVERY_MAX_POSITION_LOSS_PCT"), 0.0075)))
    minimum_net = max(0.0005, min(0.02, _f(os.environ.get("NIJA_RECOVERY_MIN_NET_PROFIT_PCT"), 0.0010)))
    activation = max(
        _venue_cost_pct(broker) + minimum_net,
        max(0.001, _f(os.environ.get("NIJA_RECOVERY_PROFIT_LOCK_ACTIVATION_PCT"), 0.0060)),
    )
    callback = max(0.001, min(0.02, _f(os.environ.get("NIJA_RECOVERY_TRAILING_CALLBACK_PCT"), 0.0025)))

    if side in {"long", "buy"}:
        stop = entry * (1.0 - max_loss)
        net_floor = entry * (1.0 + _venue_cost_pct(broker) + minimum_net)
        if market <= stop:
            return True, "recovery_max_loss_cap", stop
        high = _f(auto_exit._HIGH_WATER.get(auto_exit._position_key(pos)), market)
        if high >= entry * (1.0 + activation) and market >= net_floor and market <= high * (1.0 - callback):
            return True, "recovery_trailing_net_profit_lock", max(net_floor, high * (1.0 - callback))
        if market >= net_floor:
            return True, "recovery_fee_aware_profit_harvest", net_floor
    else:
        stop = entry * (1.0 + max_loss)
        net_floor = entry / max(1e-12, 1.0 + _venue_cost_pct(broker) + minimum_net)
        if market >= stop:
            return True, "recovery_max_loss_cap", stop
        low = _f(auto_exit._HIGH_WATER.get(auto_exit._position_key(pos)), market)
        # Some legacy trackers store a high-water value for both directions.
        # Immediate net-positive harvesting below is authoritative for shorts.
        if market <= net_floor:
            return True, "recovery_fee_aware_profit_harvest", net_floor

    return False, "", 0.0


def _trigger(broker: Any, pos: dict[str, Any], market: float) -> tuple[bool, str, float]:
    hit, reason, target = auto_exit._trigger(pos, market)
    # Existing loss protection always keeps priority.  During recovery, defer
    # ordinary profit targets long enough to apply the fee-aware recovery lock.
    reason_norm = str(reason or "").strip().lower()
    protective = any(token in reason_norm for token in ("stop_loss", "trailing_stop", "loss_cap", "liquidation"))
    if hit and protective:
        return hit, reason, target

    recovery_hit, recovery_reason, recovery_target = _recovery_position_trigger(broker, pos, market)
    if recovery_hit:
        logger.critical(
            "ACCOUNT_RECOVERY_EXIT_AMPLIFIED marker=%s venue=%s account=%s symbol=%s "
            "reason=%s target=%.8f market=%.8f exposure_added=false leverage_increased=false "
            "stop_widened=false fee_slippage_floor=true",
            _MARKER, auto_exit._broker_label(broker), _account_label(broker),
            auto_exit._sym(pos.get("symbol")), recovery_reason, recovery_target, market,
        )
        return recovery_hit, recovery_reason, recovery_target
    if hit:
        return hit, reason, target
    side = auto_exit._side(pos.get("side"), pos)
    entry = auto_exit._entry_price(pos)
    if _operator_profit_exit_active():
        operator_target = _operator_net_profit_target(broker, pos)
        if operator_target > 0:
            if side in {"long", "buy"} and market >= operator_target:
                return True, "operator_net_profit_exit", operator_target
            if side in {"short", "sell"}:
                minimum_net = max(0.0, _f(os.environ.get("NIJA_OPERATOR_MIN_NET_PROFIT_PCT"), 0.0005))
                short_target = entry / max(1e-12, (1.0 + _venue_cost_pct(broker) + minimum_net))
                if market <= short_target:
                    return True, "operator_net_profit_exit", short_target
        elif entry > 0:
            logger.warning(
                "OPERATOR_NET_PROFIT_EXIT_SKIPPED_UNVERIFIED marker=%s venue=%s account=%s symbol=%s "
                "entry=%.8f qty=%.8f cost_basis_verified=%s auto_exit_blocked=%s",
                _OPERATOR_MARKER,
                auto_exit._broker_label(broker),
                _account_label(broker),
                auto_exit._sym(pos.get("symbol")),
                entry,
                auto_exit._quantity(pos),
                pos.get("cost_basis_verified"),
                bool(pos.get("auto_exit_blocked", False)),
            )
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
    if _operator_profit_exit_active():
        logger.critical(
            "OPERATOR_NET_PROFIT_EXIT_REQUEST_ACTIVE marker=%s venue=%s account=%s request_id=%s "
            "until_epoch=%s fee_slippage_reserve_preserved=true minimum_order_unchanged=true "
            "fill_confirmation_required=true loss_liquidation=false",
            _OPERATOR_MARKER,
            venue,
            account,
            str(os.environ.get("NIJA_OPERATOR_NET_PROFIT_EXIT_REQUEST_ID", "unspecified") or "unspecified"),
            str(os.environ.get("NIJA_OPERATOR_NET_PROFIT_EXIT_UNTIL_EPOCH", "") or ""),
        )
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


def _logical_identity(broker: Any) -> tuple[str, str]:
    return (
        str(auto_exit._broker_label(broker) or "unknown").strip().lower(),
        str(_account_label(broker) or "platform").strip().lower(),
    )


def _registered_values() -> list[Any]:
    return list(_BROKERS) + list(_STRONG_BROKERS)


def _discard_broker(broker: Any) -> None:
    try:
        _BROKERS.discard(broker)
    except TypeError:
        pass
    while broker in _STRONG_BROKERS:
        _STRONG_BROKERS.remove(broker)


def _register_broker(broker: Any) -> None:
    if broker is None:
        return
    identity = _logical_identity(broker)
    replaced = None
    with _LOCK:
        for existing in _registered_values():
            if existing is broker:
                _start()
                return
            if _logical_identity(existing) == identity:
                if type(existing) is type(broker):
                    if identity not in _DUPLICATE_ACCOUNTS:
                        logger.info(
                            "UNIVERSAL_BROKER_EXIT_DUPLICATE_SKIPPED marker=%s venue=%s account=%s class=%s",
                            _MARKER,
                            identity[0],
                            identity[1],
                            type(broker).__name__,
                        )
                        _DUPLICATE_ACCOUNTS.add(identity)
                    _start()
                    return
                replaced = existing
                _discard_broker(existing)
        try:
            _BROKERS.add(broker)
        except TypeError:
            _STRONG_BROKERS.append(broker)
        _DUPLICATE_ACCOUNTS.discard(identity)
    if replaced is not None:
        logger.warning(
            "UNIVERSAL_BROKER_EXIT_REPLACED marker=%s venue=%s account=%s old_class=%s new_class=%s",
            _MARKER,
            identity[0],
            identity[1],
            type(replaced).__name__,
            type(broker).__name__,
        )
    else:
        logger.info(
            "UNIVERSAL_BROKER_EXIT_REGISTERED marker=%s venue=%s account=%s class=%s",
            _MARKER,
            identity[0],
            identity[1],
            type(broker).__name__,
        )
    _start()


def _snapshot() -> list[Any]:
    values = _registered_values()
    latest: dict[tuple[str, str], Any] = {}
    for broker in values:
        if broker is not None:
            latest[_logical_identity(broker)] = broker
    return list(latest.values())


def _start() -> None:
    global _STARTED
    if not _truthy("NIJA_UNIVERSAL_BROKER_EXIT_ENABLED", "true"):
        return
    with _LOCK:
        if bool(_STATE["started"]):
            _STARTED = True
            return
        _STATE["started"] = True
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
