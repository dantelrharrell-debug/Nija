"""Enforce net-positive Kraken profit taking and confirmed exit accounting.

The account-local Kraken exit runtime already evaluates every configured platform
and user account.  This final convergence layer strengthens two invariants:

* A normal take-profit cannot fire below the fee/slippage-adjusted net-profit
  target.  Break-even remains available only through the explicit aged
  break-even policy; emergency stop-loss exits remain untouched.
* An accepted/submitted order is not treated as a completed exit.  NIJA keeps the
  position tracked until Kraken reports a terminal fill (or the broker position
  disappears), preventing false profit records and duplicate close attempts.

No fill or profit is guaranteed.  Market movement, spread, slippage, exchange
minimums and emergency risk controls remain authoritative.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping, MutableMapping, Optional

logger = logging.getLogger("nija.kraken_profit_realization_guard")
_MARKER = "20260714-kraken-profit-realization-v1"
_PATCH_ATTR = "_nija_kraken_profit_realization_v1"
_LOCK = threading.RLock()
_ORIGINAL_IMPORT = None
_PATCHED: set[tuple[str, int]] = set()
_PENDING: dict[tuple[str, str], dict[str, Any]] = {}
_PENDING_LOCK = threading.RLock()

_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_CONFIRMED = {"filled", "closed", "done", "complete", "completed", "success", "executed"}
_PENDING_STATES = {"accepted", "submitted", "pending", "open", "new", "working", "partially_filled"}
_FAILED = {"failed", "error", "rejected", "canceled", "cancelled", "expired", "void"}
_EMERGENCY_REASONS = {"emergency_stop_loss", "critical_margin_reduction", "liquidation_prevention"}
_BREAK_EVEN_REASONS = {"fee_adjusted_break_even", "profit_lock_break_even"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value or 0.0)
        return parsed if parsed == parsed else default
    except Exception:
        return default


def _status(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    for key in ("status", "state", "order_status", "result_status"):
        text = str(payload.get(key) or "").strip().lower().replace("-", "_").replace(" ", "_")
        if text:
            return text
    result = payload.get("result")
    if isinstance(result, Mapping):
        return _status(result)
    return ""


def _order_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    for key in ("order_id", "id", "txid", "transaction_id", "client_order_id"):
        value = payload.get(key)
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        text = str(value or "").strip()
        if text:
            return text
    result = payload.get("result")
    if isinstance(result, Mapping):
        return _order_id(result)
    return ""


def _filled_quantity(payload: Any) -> float:
    if not isinstance(payload, Mapping):
        return 0.0
    for key in ("filled_quantity", "filled_qty", "executed_qty", "vol_exec", "filled", "amount_filled"):
        value = _f(payload.get(key))
        if value > 0:
            return value
    result = payload.get("result")
    if isinstance(result, Mapping):
        return _filled_quantity(result)
    return 0.0


def _query_order(broker: Any, order_id: str) -> Mapping[str, Any]:
    if not order_id:
        return {}
    for method_name in ("get_order_status", "get_order", "fetch_order", "query_order", "get_order_by_id"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                result = method(order_id)
            except TypeError:
                result = method(order_id=order_id)
            if isinstance(result, Mapping):
                return result
        except Exception:
            continue
    private_call = getattr(broker, "_kraken_api_call", None)
    if callable(private_call):
        try:
            payload = private_call("QueryOrders", {"txid": order_id, "trades": True})
            if isinstance(payload, Mapping):
                result = payload.get("result")
                if isinstance(result, Mapping):
                    row = result.get(order_id)
                    if isinstance(row, Mapping):
                        return row
                    if result and all(isinstance(value, Mapping) for value in result.values()):
                        return next(iter(result.values()))
                return payload
        except Exception:
            pass
    return {}


def _is_short(position: Mapping[str, Any]) -> bool:
    return str(position.get("side") or "long").strip().lower() in {"short", "sell"}


def _meets(price: float, threshold: float, short: bool) -> bool:
    return price <= threshold if short else price >= threshold


def _patch_thresholds(module: ModuleType) -> bool:
    current = getattr(module, "_exit_thresholds", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current))

    @wraps(current)
    def exit_thresholds(account: str, symbol: str, entry: float):
        breakeven, target = current(account, symbol, entry)
        entry_value = max(0.0, _f(entry))
        reserve = max(0.0, _f(os.environ.get("NIJA_KRAKEN_EXIT_SLIPPAGE_RESERVE_PCT"), 0.0015))
        minimum_net = max(0.001, _f(os.environ.get("NIJA_KRAKEN_MIN_REALIZED_NET_PROFIT_PCT"), 0.004))
        if entry_value <= 0:
            return breakeven, target
        adjusted_breakeven = max(_f(breakeven), entry_value * (1.0 + reserve))
        adjusted_target = max(_f(target), adjusted_breakeven + entry_value * minimum_net)
        return adjusted_breakeven, adjusted_target

    setattr(exit_thresholds, _PATCH_ATTR, True)
    setattr(exit_thresholds, "__wrapped__", current)
    module._exit_thresholds = exit_thresholds
    return True


def _patch_exit_reason(module: ModuleType) -> bool:
    current = getattr(module, "_exit_reason", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current))

    @wraps(current)
    def exit_reason(position: Mapping[str, Any], price: float, account: str, symbol: str):
        reason, breakeven, target = current(position, price, account, symbol)
        if not reason or reason in _EMERGENCY_REASONS:
            return reason, breakeven, target
        short = _is_short(position)
        market = _f(price)
        at_breakeven = _meets(market, _f(breakeven), short)
        at_target = _meets(market, _f(target), short)

        if reason in _BREAK_EVEN_REASONS:
            if at_breakeven:
                return reason, breakeven, target
            logger.error(
                "KRAKEN_BREAK_EVEN_EXIT_SUPPRESSED marker=%s account=%s symbol=%s reason=%s market=%.10f breakeven=%.10f",
                _MARKER, account, symbol, reason, market, _f(breakeven),
            )
            return None, breakeven, target

        # Explicit take-profit values can be stale or gross-of-fees.  Normal profit
        # exits must clear the canonical fee/slippage-adjusted net target.
        if str(reason).startswith("take_profit") or reason == "net_profit_target":
            if at_target:
                logger.critical(
                    "KRAKEN_NET_PROFIT_REALIZATION_READY marker=%s account=%s symbol=%s reason=%s market=%.10f target=%.10f",
                    _MARKER, account, symbol, reason, market, _f(target),
                )
                return reason, breakeven, target
            logger.warning(
                "KRAKEN_TAKE_PROFIT_BELOW_NET_FLOOR_SUPPRESSED marker=%s account=%s symbol=%s reason=%s market=%.10f breakeven=%.10f target=%.10f",
                _MARKER, account, symbol, reason, market, _f(breakeven), _f(target),
            )
            return None, breakeven, target
        return reason, breakeven, target

    setattr(exit_reason, _PATCH_ATTR, True)
    setattr(exit_reason, "__wrapped__", current)
    module._exit_reason = exit_reason
    return True


def _tracker_apply_fill(broker: Any, symbol: str, requested: float, filled: float = 0.0) -> None:
    tracker = getattr(broker, "position_tracker", None)
    method = getattr(tracker, "track_exit", None)
    if not callable(method):
        return
    try:
        if filled > 0 and requested > 0 and filled < requested * 0.999:
            method(symbol, filled)
        else:
            method(symbol)
    except Exception:
        logger.exception("KRAKEN_CONFIRMED_EXIT_TRACKER_UPDATE_FAILED marker=%s symbol=%s", _MARKER, symbol)


def _pending_confirmation(broker: Any, pending: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    payload = _query_order(broker, str(pending.get("order_id") or ""))
    status = _status(payload)
    if status in _CONFIRMED:
        return "confirmed", payload
    if status in _FAILED:
        return "failed", payload
    return "pending", payload


def _replace_scan(module: ModuleType) -> bool:
    current = getattr(module, "_scan_account_exits", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current))

    def scan_account_exits(trader: Any, identity: str, broker: Any) -> int:
        if not _truthy("NIJA_KRAKEN_ALL_ACCOUNT_EXIT_ENABLED", "true") or not module._is_kraken(broker):
            return 0
        account = module._identity(broker, identity)
        ready, private_reason = module._private_ready(broker, account)
        if not ready:
            logger.warning(
                "KRAKEN_ACCOUNT_EXIT_SCAN_BLOCKED marker=%s account=%s reason=%s",
                _MARKER, account, private_reason,
            )
            return 0

        closed = 0
        for position in list(module._position_rows(broker)):
            symbol = module._normalise_symbol(position.get("symbol"))
            quantity = module._quantity(position)
            entry = module._entry_price(position)
            if not symbol or quantity <= 0:
                continue
            key = (account, symbol)

            with _PENDING_LOCK:
                pending = dict(_PENDING.get(key) or {})
            if pending:
                state, payload = _pending_confirmation(broker, pending)
                if state == "confirmed":
                    filled = _filled_quantity(payload)
                    _tracker_apply_fill(broker, symbol, _f(pending.get("quantity")), filled)
                    with _PENDING_LOCK:
                        _PENDING.pop(key, None)
                    module._EXIT_STATE.pop(key, None)
                    closed += 1
                    logger.critical(
                        "KRAKEN_ACCOUNT_EXIT_ORDER_ACK_CONFIRMED marker=%s account=%s symbol=%s reason=%s order_id=%s status=%s filled_qty=%.8f",
                        _MARKER, account, symbol, pending.get("reason"), pending.get("order_id"), _status(payload), filled,
                    )
                    continue
                if state == "failed":
                    with _PENDING_LOCK:
                        _PENDING.pop(key, None)
                    logger.error(
                        "KRAKEN_ACCOUNT_EXIT_ORDER_TERMINAL_FAILURE marker=%s account=%s symbol=%s order_id=%s status=%s",
                        _MARKER, account, symbol, pending.get("order_id"), _status(payload),
                    )
                else:
                    age = max(0.0, time.time() - _f(pending.get("submitted_at"), time.time()))
                    logger.warning(
                        "KRAKEN_ACCOUNT_EXIT_ORDER_PENDING marker=%s account=%s symbol=%s order_id=%s age_s=%.1f tracker_preserved=true duplicate_submit_blocked=true",
                        _MARKER, account, symbol, pending.get("order_id"), age,
                    )
                    continue

            pair = module._resolve_pair(broker, symbol)
            if not pair:
                continue
            price = module._ticker_price(broker, pair)
            if price <= 0:
                logger.warning(
                    "KRAKEN_ACCOUNT_EXIT_PRICE_MISSING marker=%s account=%s symbol=%s pair=%s",
                    _MARKER, account, symbol, pair,
                )
                continue
            reason, breakeven, target = module._exit_reason(position, price, account, symbol)
            logger.info(
                "KRAKEN_ACCOUNT_EXIT_EVALUATED marker=%s account=%s symbol=%s pair=%s qty=%.8f entry=$%.8f market=$%.8f breakeven=$%.8f profit_target=$%.8f decision=%s",
                _MARKER, account, symbol, pair, quantity, entry, price, breakeven, target, reason or "hold",
            )
            if not reason:
                continue

            with module._EXIT_LOCK:
                if key in module._ACTIVE_EXITS:
                    continue
                module._ACTIVE_EXITS.add(key)
            try:
                logger.critical(
                    "KRAKEN_ACCOUNT_EXIT_TRIGGER marker=%s account=%s symbol=%s pair=%s reason=%s market=$%.8f breakeven=$%.8f profit_target=$%.8f",
                    _MARKER, account, symbol, pair, reason, price, breakeven, target,
                )
                result = module._submit_exit(broker, account, pair, quantity, reason)
                status = _status(result)
                order_id = _order_id(result)
                filled = _filled_quantity(result)
                if status in _CONFIRMED:
                    _tracker_apply_fill(broker, symbol, quantity, filled)
                    module._EXIT_STATE.pop(key, None)
                    closed += 1
                    logger.critical(
                        "KRAKEN_ACCOUNT_EXIT_ORDER_ACK_CONFIRMED marker=%s account=%s symbol=%s reason=%s order_id=%s status=%s filled_qty=%.8f",
                        _MARKER, account, symbol, reason, order_id, status, filled,
                    )
                elif order_id and (status in _PENDING_STATES or not status):
                    with _PENDING_LOCK:
                        _PENDING[key] = {
                            "order_id": order_id,
                            "submitted_at": time.time(),
                            "quantity": quantity,
                            "pair": pair,
                            "reason": reason,
                        }
                    logger.critical(
                        "KRAKEN_ACCOUNT_EXIT_ORDER_ACCEPTED_PENDING_FILL marker=%s account=%s symbol=%s reason=%s order_id=%s status=%s tracker_preserved=true",
                        _MARKER, account, symbol, reason, order_id, status or "unknown",
                    )
                else:
                    logger.error(
                        "KRAKEN_ACCOUNT_EXIT_ORDER_FAILED marker=%s account=%s symbol=%s reason=%s status=%s error=%s",
                        _MARKER, account, symbol, reason, status, result.get("error", result) if isinstance(result, Mapping) else result,
                    )
            finally:
                with module._EXIT_LOCK:
                    module._ACTIVE_EXITS.discard(key)
        return closed

    setattr(scan_account_exits, _PATCH_ATTR, True)
    setattr(scan_account_exits, "__wrapped__", current)
    module._scan_account_exits = scan_account_exits
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    if not str(getattr(module, "__name__", "")).endswith("kraken_all_account_exit_runtime_patch"):
        return False
    changed = _patch_thresholds(module)
    changed = _patch_exit_reason(module) or changed
    changed = _replace_scan(module) or changed
    if changed:
        _PATCHED.add(key)
        logger.critical(
            "KRAKEN_PROFIT_REALIZATION_GUARD_PATCHED marker=%s net_positive_take_profit=true confirmed_fill_accounting=true",
            _MARKER,
        )
    return changed


def _patch_loaded() -> None:
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception:
                continue


def _set_defaults() -> None:
    defaults = {
        "NIJA_KRAKEN_ALL_ACCOUNT_EXIT_ENABLED": "true",
        "NIJA_KRAKEN_EXIT_ROUND_TRIP_COST_PCT": "0.008",
        "NIJA_KRAKEN_EXIT_SLIPPAGE_RESERVE_PCT": "0.0015",
        "NIJA_KRAKEN_EXIT_NET_PROFIT_TARGET_PCT": "0.004",
        "NIJA_KRAKEN_MIN_REALIZED_NET_PROFIT_PCT": "0.004",
        "NIJA_KRAKEN_BREAK_EVEN_EXIT_ENABLED": "true",
        "NIJA_KRAKEN_BREAK_EVEN_MAX_HOLD_MINUTES": "60",
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, value)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _set_defaults()
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = builtins.__import__
            local = threading.local()

            def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                if getattr(local, "active", False):
                    return module
                local.active = True
                try:
                    _patch_loaded()
                finally:
                    local.active = False
                return module

            builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    os.environ["NIJA_KRAKEN_PROFIT_REALIZATION_GUARD_INSTALLED"] = "1"
    logger.critical(
        "KRAKEN_PROFIT_REALIZATION_GUARD_INSTALLED marker=%s round_trip=%s slippage_reserve=%s minimum_net_profit=%s break_even_after_min=%s",
        _MARKER,
        os.environ.get("NIJA_KRAKEN_EXIT_ROUND_TRIP_COST_PCT"),
        os.environ.get("NIJA_KRAKEN_EXIT_SLIPPAGE_RESERVE_PCT"),
        os.environ.get("NIJA_KRAKEN_MIN_REALIZED_NET_PROFIT_PCT"),
        os.environ.get("NIJA_KRAKEN_BREAK_EVEN_MAX_HOLD_MINUTES"),
    )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_status",
    "_order_id",
    "_filled_quantity",
    "_patch_thresholds",
    "_patch_exit_reason",
    "_replace_scan",
]
