"""Fill-confirmed, fee-aware exit convergence for all live NIJA brokers.

This module hardens the existing universal broker exit supervisor without
weakening any writer, activation, risk, capital, or venue-local readiness gate.
It fixes three concrete failure modes:

* an exchange acknowledgement such as ``accepted`` is not a confirmed fill and
  must never cause a held position to be marked closed;
* the existing fee-aware target used a long-position formula for shorts;
* brokers created before/through alternate manager paths must still be
  registered with the universal exit supervisor.

Profit cannot be guaranteed.  This guard only permits profit exits after the
configured fee, slippage, and minimum-net-profit reserve has been cleared, and
it keeps loss exits available regardless of that profit floor.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from bot import auto_exit_sl_tp_runtime_patch as auto_exit
from bot import universal_broker_exit_supervisor_patch as supervisor

logger = logging.getLogger("nija.live_broker_profit_exit_convergence")

_MARKER = "20260723-live-broker-profit-exit-v25"
_LOCK = threading.RLock()
_INSTALLED = False
_RECONCILER_STARTED = False
_ORIGINAL_TRIGGER = supervisor._trigger
_ORIGINAL_SCAN = supervisor._scan_broker
_PENDING: dict[str, "PendingExit"] = {}


@dataclass
class PendingExit:
    broker: Any
    position: dict[str, Any]
    order: dict[str, Any]
    reason: str
    market: float
    created_at: float
    deadline: float


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y"
    }


def _status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("status") or payload.get("state") or payload.get("order_status") or "").strip().lower()


def _filled_quantity(payload: Any) -> float:
    if not isinstance(payload, dict):
        return 0.0
    return max(
        _f(payload.get("filled_size")),
        _f(payload.get("filled_qty")),
        _f(payload.get("filled_quantity")),
        _f(payload.get("executed_qty")),
        _f(payload.get("cum_exec_qty")),
        _f(payload.get("dealSize")),
    )


def _is_filled(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    state = _status(payload)
    if state in {"filled", "closed", "done", "complete", "completed", "settled"}:
        return True
    return _filled_quantity(payload) > 0 and state not in {
        "error", "failed", "rejected", "cancelled", "canceled", "expired"
    }


def _is_terminal_failure(payload: Any) -> bool:
    return _status(payload) in {
        "error", "failed", "rejected", "cancelled", "canceled", "expired"
    }


def _order_id(payload: Any) -> str:
    return str(auto_exit._get(payload, "order_id", "id", "txid", "ordId", "client_order_id", default="") or "")


def _query_order(broker: Any, order: dict[str, Any], symbol: str) -> dict[str, Any]:
    oid = _order_id(order)
    if not oid:
        return {}
    calls = (
        ("get_order_status", ({"order_id": oid, "symbol": symbol}, {"order_id": oid}, {"id": oid})),
        ("get_order", ({"order_id": oid, "symbol": symbol}, {"order_id": oid}, {"id": oid})),
        ("fetch_order", ({"id": oid, "symbol": symbol}, {"id": oid}, {"order_id": oid})),
        ("query_order", ({"order_id": oid, "symbol": symbol}, {"order_id": oid}, {"ordId": oid})),
    )
    for method_name, variants in calls:
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        for kwargs in variants:
            try:
                result = method(**kwargs)
                if isinstance(result, dict):
                    nested = result.get("order") or result.get("data")
                    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                        return nested[0]
                    if isinstance(nested, dict):
                        return nested
                    return result
            except TypeError:
                continue
            except Exception as exc:
                logger.warning(
                    "LIVE_EXIT_ORDER_QUERY_FAILED marker=%s venue=%s symbol=%s order_id=%s method=%s err=%s:%s",
                    _MARKER, auto_exit._broker_label(broker), symbol, oid, method_name,
                    type(exc).__name__, exc,
                )
                break
        try:
            result = method(oid)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    return {}


def _round_trip_reserve_pct(broker: Any) -> float:
    label = auto_exit._broker_label(broker)
    venue_default = 0.014
    if "kraken" in label:
        venue_default = 0.008
    elif "okx" in label:
        venue_default = 0.004
    fees = max(
        0.0,
        _f(
            os.environ.get(f"NIJA_{label.upper()}_ROUND_TRIP_FEE_PCT"),
            _f(os.environ.get("NIJA_EXIT_ROUND_TRIP_FEE_PCT"), venue_default),
        ),
    )
    slippage = max(0.0, _f(os.environ.get("NIJA_EXIT_SLIPPAGE_RESERVE_PCT"), 0.0015))
    minimum_net = max(0.0, _f(os.environ.get("NIJA_MINIMUM_NET_PROFIT_PCT"), 0.004))
    return fees + slippage + minimum_net


def _fee_aware_profit_target(broker: Any, pos: dict[str, Any]) -> float:
    entry = auto_exit._entry_price(pos)
    if entry <= 0:
        return 0.0
    reserve = _round_trip_reserve_pct(broker)
    side = auto_exit._side(pos.get("side"), pos)
    if side in {"short", "sell"}:
        return max(0.0, entry * (1.0 - reserve))
    return entry * (1.0 + reserve)


def _profit_reason(reason: str) -> bool:
    text = str(reason or "").lower()
    return any(token in text for token in ("take_profit", "profit_lock", "net_profit", "trailing_tp"))


def _trigger(broker: Any, pos: dict[str, Any], market: float) -> tuple[bool, str, float]:
    hit, reason, target = _ORIGINAL_TRIGGER(broker, pos, market)
    if not hit:
        return hit, reason, target
    if not _profit_reason(reason):
        return hit, reason, target

    floor = _fee_aware_profit_target(broker, pos)
    side = auto_exit._side(pos.get("side"), pos)
    clears_floor = market <= floor if side in {"short", "sell"} else market >= floor
    if clears_floor:
        return True, reason, max(target, floor) if side not in {"short", "sell"} else min(target or floor, floor)

    logger.info(
        "LIVE_EXIT_PROFIT_FLOOR_WAIT marker=%s venue=%s account=%s symbol=%s reason=%s market=%.8f required=%.8f reserve_pct=%.6f",
        _MARKER, auto_exit._broker_label(broker), supervisor._account_label(broker),
        auto_exit._sym(pos.get("symbol")), reason, market, floor,
        _round_trip_reserve_pct(broker),
    )
    return False, "", 0.0


def _pending_key(broker: Any, pos: dict[str, Any]) -> str:
    symbol = auto_exit._sym(pos.get("symbol"))
    pid = str(pos.get("position_id") or symbol)
    return f"{id(broker)}:{pid}:{symbol}"


def _confirm_and_close(pending: PendingExit, payload: dict[str, Any]) -> bool:
    broker = pending.broker
    pos = pending.position
    symbol = auto_exit._sym(pos.get("symbol"))
    if not _is_filled(payload):
        return False
    merged = dict(pending.order)
    merged.update(payload)
    supervisor._mark_closed(broker, pos, merged, pending.reason, pending.market)
    auto_exit._HIGH_WATER.pop(auto_exit._position_key(pos), None)
    logger.critical(
        "LIVE_BROKER_EXIT_FILL_CONFIRMED marker=%s venue=%s account=%s symbol=%s reason=%s order_id=%s status=%s",
        _MARKER, auto_exit._broker_label(broker), supervisor._account_label(broker),
        symbol, pending.reason, _order_id(merged), _status(merged),
    )
    return True


def _scan_broker(broker: Any) -> int:
    closed = 0
    account = supervisor._account_label(broker)
    venue = auto_exit._broker_label(broker)
    now = time.monotonic()
    positions = supervisor._tracker_positions(broker)

    for pos in positions:
        symbol = auto_exit._sym(pos.get("symbol"))
        pid = str(pos.get("position_id") or symbol)
        key = _pending_key(broker, pos)
        pending = _PENDING.get(key)
        if pending is not None:
            status_payload = _query_order(broker, pending.order, symbol)
            if _confirm_and_close(pending, status_payload):
                closed += 1
                _PENDING.pop(key, None)
                supervisor._ACTIVE.discard(key)
                continue
            if _is_terminal_failure(status_payload):
                logger.error(
                    "LIVE_BROKER_EXIT_TERMINAL_FAILURE marker=%s venue=%s account=%s symbol=%s order_id=%s status=%s",
                    _MARKER, venue, account, symbol, _order_id(pending.order), _status(status_payload),
                )
                _PENDING.pop(key, None)
                supervisor._ACTIVE.discard(key)
                continue
            if now < pending.deadline:
                logger.info(
                    "LIVE_BROKER_EXIT_FILL_PENDING marker=%s venue=%s account=%s symbol=%s order_id=%s status=%s",
                    _MARKER, venue, account, symbol, _order_id(pending.order), _status(status_payload) or "unknown",
                )
                continue
            logger.error(
                "LIVE_BROKER_EXIT_FILL_TIMEOUT marker=%s venue=%s account=%s symbol=%s order_id=%s action=reconcile_before_retry",
                _MARKER, venue, account, symbol, _order_id(pending.order),
            )
            _PENDING.pop(key, None)
            supervisor._ACTIVE.discard(key)
            continue

        entry = auto_exit._entry_price(pos)
        qty = auto_exit._quantity(pos)
        if entry <= 0 or qty <= 0:
            logger.warning(
                "LIVE_EXIT_SKIPPED_UNVERIFIED_POSITION marker=%s venue=%s account=%s symbol=%s entry=%.8f qty=%.8f no_cost_basis_fabrication=true",
                _MARKER, venue, account, symbol, entry, qty,
            )
            continue
        market = auto_exit._price(broker, symbol)
        if market <= 0:
            logger.warning(
                "LIVE_EXIT_PRICE_UNAVAILABLE marker=%s venue=%s account=%s symbol=%s",
                _MARKER, venue, account, symbol,
            )
            continue
        hit, reason, target = _trigger(broker, pos, market)
        if not hit:
            continue

        supervisor._ACTIVE.add(key)
        logger.critical(
            "LIVE_BROKER_EXIT_TRIGGER marker=%s venue=%s account=%s symbol=%s reason=%s target=%.8f market=%.8f entry=%.8f qty=%.8f",
            _MARKER, venue, account, symbol, reason, target, market, entry, qty,
        )
        order = auto_exit._exit_order(broker, pos, market)
        if not isinstance(order, dict) or not auto_exit._ok(order):
            logger.error(
                "LIVE_BROKER_EXIT_SUBMIT_FAILED marker=%s venue=%s account=%s symbol=%s reason=%s error=%s",
                _MARKER, venue, account, symbol, reason, order,
            )
            supervisor._ACTIVE.discard(key)
            continue

        pending_exit = PendingExit(
            broker=broker,
            position=dict(pos),
            order=dict(order),
            reason=reason,
            market=market,
            created_at=now,
            deadline=now + max(5.0, _f(os.environ.get("NIJA_EXIT_FILL_CONFIRM_TIMEOUT_S"), 30.0)),
        )
        if _confirm_and_close(pending_exit, order):
            closed += 1
            supervisor._ACTIVE.discard(key)
            continue
        if not _order_id(order):
            logger.error(
                "LIVE_BROKER_EXIT_UNCONFIRMED_NO_ORDER_ID marker=%s venue=%s account=%s symbol=%s status=%s position_remains_open=true",
                _MARKER, venue, account, symbol, _status(order) or "unknown",
            )
            supervisor._ACTIVE.discard(key)
            continue
        _PENDING[key] = pending_exit
        logger.warning(
            "LIVE_BROKER_EXIT_SUBMITTED_AWAITING_FILL marker=%s venue=%s account=%s symbol=%s order_id=%s status=%s",
            _MARKER, venue, account, symbol, _order_id(order), _status(order) or "accepted",
        )
    return closed


def _iter_manager_brokers() -> list[Any]:
    brokers: list[Any] = []
    try:
        manager_module = sys.modules.get("bot.multi_account_broker_manager")
        if manager_module is None:
            return brokers
        manager = getattr(manager_module, "multi_account_broker_manager", None)
        if manager is None:
            getter = getattr(manager_module, "get_broker_manager", None)
            manager = getter() if callable(getter) else None
        if manager is None:
            return brokers
        platform = getattr(manager, "_platform_brokers", {})
        if isinstance(platform, dict):
            brokers.extend(platform.values())
        users = getattr(manager, "user_brokers", {})
        if isinstance(users, dict):
            for per_user in users.values():
                if isinstance(per_user, dict):
                    brokers.extend(per_user.values())
        all_users = getattr(manager, "_all_user_brokers", {})
        if isinstance(all_users, dict):
            brokers.extend(all_users.values())
    except Exception as exc:
        logger.warning("LIVE_BROKER_REGISTRY_RECONCILE_FAILED marker=%s err=%s:%s", _MARKER, type(exc).__name__, exc)
    return [broker for broker in brokers if broker is not None]


def _configured_venues() -> dict[str, bool]:
    return {
        "kraken": bool((os.environ.get("KRAKEN_PLATFORM_API_KEY") or os.environ.get("KRAKEN_API_KEY")) and (os.environ.get("KRAKEN_PLATFORM_API_SECRET") or os.environ.get("KRAKEN_API_SECRET"))),
        "coinbase": bool(os.environ.get("COINBASE_API_KEY") and os.environ.get("COINBASE_API_SECRET")),
        "okx": bool(os.environ.get("OKX_API_KEY") and os.environ.get("OKX_API_SECRET") and os.environ.get("OKX_PASSPHRASE")),
    }


def _reconcile_brokers_once() -> dict[str, bool]:
    for broker in _iter_manager_brokers():
        supervisor._register_broker(broker)
    connected = {"kraken": False, "coinbase": False, "okx": False}
    for broker in supervisor._snapshot():
        label = auto_exit._broker_label(broker)
        for venue in connected:
            if venue in label and bool(getattr(broker, "connected", False)):
                connected[venue] = True
    configured = _configured_venues()
    logger.warning(
        "LIVE_BROKER_CONNECTIVITY_SNAPSHOT marker=%s kraken_configured=%s kraken_connected=%s coinbase_configured=%s coinbase_connected=%s okx_configured=%s okx_connected=%s all_configured_connected=%s",
        _MARKER,
        configured["kraken"], connected["kraken"],
        configured["coinbase"], connected["coinbase"],
        configured["okx"], connected["okx"],
        all((not configured[name]) or connected[name] for name in configured),
    )
    return connected


def _start_reconciler() -> None:
    global _RECONCILER_STARTED
    with _LOCK:
        if _RECONCILER_STARTED:
            return
        _RECONCILER_STARTED = True

    def loop() -> None:
        interval = max(5.0, _f(os.environ.get("NIJA_LIVE_BROKER_RECONCILE_SECONDS"), 30.0))
        logger.critical(
            "LIVE_BROKER_PROFIT_EXIT_RECONCILER_STARTED marker=%s interval_s=%.1f venues=kraken,coinbase,okx fill_confirmation=true",
            _MARKER, interval,
        )
        while _truthy("NIJA_LIVE_BROKER_PROFIT_EXIT_V25_ENABLED", "true"):
            try:
                _reconcile_brokers_once()
            except Exception as exc:
                logger.exception("LIVE_BROKER_PROFIT_EXIT_RECONCILE_FAILED marker=%s err=%s", _MARKER, exc)
            time.sleep(interval)

    threading.Thread(target=loop, name="LiveBrokerProfitExitV25", daemon=True).start()


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            _reconcile_brokers_once()
            return True
        os.environ.setdefault("NIJA_LIVE_BROKER_PROFIT_EXIT_V25_ENABLED", "true")
        os.environ.setdefault("NIJA_EXIT_FILL_CONFIRM_TIMEOUT_S", "30")
        os.environ.setdefault("NIJA_LIVE_BROKER_RECONCILE_SECONDS", "30")
        os.environ.setdefault("NIJA_MINIMUM_NET_PROFIT_PCT", "0.004")
        os.environ.setdefault("NIJA_EXIT_SLIPPAGE_RESERVE_PCT", "0.0015")
        supervisor._fee_aware_profit_target = _fee_aware_profit_target
        supervisor._trigger = _trigger
        supervisor._scan_broker = _scan_broker
        _INSTALLED = True
        os.environ["NIJA_LIVE_BROKER_PROFIT_EXIT_V25_INSTALLED"] = "1"
        _reconcile_brokers_once()
        _start_reconciler()
        logger.critical(
            "LIVE_BROKER_PROFIT_EXIT_V25_INSTALLED marker=%s fill_confirmed=true fee_aware_long_short=true held_positions=true venues=kraken,coinbase,okx",
            _MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install", "install_import_hook", "_is_filled", "_fee_aware_profit_target",
    "_trigger", "_scan_broker", "_reconcile_brokers_once",
]
