"""Universal broker exit fill reconciliation v67.

The legacy universal exit path treated an accepted order or a bare ``order_id``
as a completed exit.  That is not a portable exchange contract: order
acceptance and order execution are separate lifecycle states on Coinbase, OKX,
Alpaca, Binance and other venues.

v67 establishes one broker-agnostic invariant for every platform/user account:

    SUBMIT ONCE -> PENDING/UNKNOWN -> RECONCILE -> CONFIRMED FILL -> LOCAL CLOSE

Safety properties
-----------------
* ``accepted``, ``new``, ``open``, ``live``, ``pending`` and
  ``partially_filled`` are never treated as fully closed.
* a response with only an order id is pending, not a fill;
* transport timeout/unknown status is preserved for reconciliation and is not
  blindly resubmitted;
* terminal fill can be proven by terminal filled state, full executed quantity,
  or native broker position disappearance/reduction to zero;
* explicit rejection/cancel/expiry clears the pending latch so the next scan may
  safely reassess the still-open position;
* current and future broker instances are discovered from canonical broker/account
  registries by capability, not by a fixed class-name allow-list;
* while this universal supervisor is enabled, the older ExecutionEngine auto-exit
  scanner is delegated/disabled to avoid two independent exit authorities
  submitting duplicate closes.

This patch does not weaken stop-loss/take-profit triggers.  It only strengthens
execution confirmation and account/venue routing.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.universal_exit_fill_reconciliation_v67")
MARKER = "20260809-universal-exit-fill-reconciliation-v67"
_INSTALL_LOCK = threading.RLock()
_PATCHED_ATTR = "_nija_universal_exit_fill_reconciliation_v67"

_FILLED_STATES = {"filled", "closed", "done", "complete", "completed", "executed"}
_PENDING_STATES = {
    "accepted", "submitted", "pending", "pending_new", "new", "open", "live",
    "working", "partially_filled", "partial_fill", "pending_cancel", "pending_replace",
    "accepted_for_bidding", "stopped", "calculated", "unknown", "timeout", "ambiguous",
}
_FAILED_STATES = {
    "failed", "error", "rejected", "canceled", "cancelled", "expired", "void",
    "mmp_canceled", "done_for_day",
}
_PENDING: dict[tuple[int, str, str], dict[str, Any]] = {}
_PENDING_LOCK = threading.RLock()
# Terminal local rejects must not be resubmitted on every supervisor scan.
# The key is process-local and includes broker identity, position id, and symbol.
_RETRY_AFTER: dict[tuple[int, str, str], float] = {}
_LAST_DELEGATE_LOG = 0.0

_BELOW_MINIMUM_REJECT = "below_minimum_exit_non_executable"


def _terminal_retry_cooldown_s(result: Mapping[str, Any]) -> float:
    """Return a bounded retry delay for deterministic, non-executable exits."""
    detail = " ".join(
        str(result.get(key) or "") for key in ("error", "reason", "reason_code", "message")
    ).strip().lower()
    if _BELOW_MINIMUM_REJECT not in detail:
        return 0.0
    try:
        configured = float(os.environ.get("NIJA_BELOW_MINIMUM_EXIT_RETRY_S", "900"))
    except (TypeError, ValueError, OverflowError):
        configured = 900.0
    # Never allow a bad environment value to restore a hot retry loop.
    return min(86400.0, max(60.0, configured))


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if result == result else default


def _status(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    for key in ("status", "state", "order_status", "result_status"):
        state = _norm(payload.get(key))
        if state:
            return state
    result = payload.get("result")
    if isinstance(result, Mapping):
        return _status(result)
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return _status(data[0])
    return ""


def _order_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    for key in ("order_id", "id", "ordId", "txid", "transaction_id", "client_order_id", "clOrdId"):
        value = payload.get(key)
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        text = str(value or "").strip()
        if text:
            return text
    result = payload.get("result")
    if isinstance(result, Mapping):
        nested = _order_id(result)
        if nested:
            return nested
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return _order_id(data[0])
    return ""


def _filled_quantity(payload: Any) -> float:
    if not isinstance(payload, Mapping):
        return 0.0
    for key in (
        "filled_quantity", "filled_qty", "executed_qty", "executedQty", "vol_exec",
        "filled_size", "filledSize", "accFillSz", "cum_qty", "cumQty", "amount_filled",
    ):
        value = _f(payload.get(key))
        if value > 0.0:
            return value
    result = payload.get("result")
    if isinstance(result, Mapping):
        nested = _filled_quantity(result)
        if nested > 0.0:
            return nested
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return _filled_quantity(data[0])
    return 0.0


def _filled_price(payload: Any, default: float = 0.0) -> float:
    if not isinstance(payload, Mapping):
        return default
    for key in (
        "filled_price", "average_fill_price", "avg_price", "avgPx", "fillPx",
        "price", "average_price",
    ):
        value = _f(payload.get(key))
        if value > 0.0:
            return value
    result = payload.get("result")
    if isinstance(result, Mapping):
        return _filled_price(result, default)
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return _filled_price(data[0], default)
    return default


def _is_full_fill(payload: Any, expected_qty: float) -> bool:
    state = _status(payload)
    if state in _FILLED_STATES:
        return True
    filled = _filled_quantity(payload)
    return bool(expected_qty > 0.0 and filled >= expected_qty * 0.999)


def _is_terminal_failure(payload: Any) -> bool:
    return _status(payload) in _FAILED_STATES


def _is_submission_ack(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    state = _status(payload)
    if state in _PENDING_STATES or state in _FILLED_STATES:
        return True
    if _order_id(payload):
        return True
    # Some wrappers expose request success separately from execution state.
    return bool(payload.get("success") is True or payload.get("accepted") is True)


def _broker_symbol_positions(broker: Any) -> list[Any]:
    for name in ("get_positions", "list_positions", "get_open_positions"):
        method = getattr(broker, name, None)
        if not callable(method):
            continue
        try:
            rows = method() or []
        except Exception:
            continue
        if isinstance(rows, Mapping):
            return list(rows.values())
        try:
            return list(rows)
        except TypeError:
            return []
    tracker = getattr(broker, "position_tracker", None)
    if tracker is not None:
        for name in ("get_all_positions", "get_open_positions", "list_positions"):
            method = getattr(tracker, name, None)
            if callable(method):
                try:
                    rows = method() or []
                    if isinstance(rows, Mapping):
                        return list(rows.values())
                    return list(rows)
                except Exception:
                    continue
    return []


def _position_quantity_for_symbol(universal: ModuleType, broker: Any, symbol: str) -> tuple[bool, float]:
    rows = _broker_symbol_positions(broker)
    if not rows:
        # Empty native list is valid evidence only if a positions API exists.
        has_api = any(
            callable(getattr(broker, name, None))
            for name in ("get_positions", "list_positions", "get_open_positions")
        )
        return has_api, 0.0
    target = universal.auto_exit._sym(symbol)
    total = 0.0
    observed = False
    for raw in rows:
        pos = raw if isinstance(raw, Mapping) else dict(getattr(raw, "__dict__", {}) or {})
        sym = universal.auto_exit._sym(pos.get("symbol") or pos.get("pair"))
        if sym != target:
            continue
        observed = True
        total += universal.auto_exit._quantity(dict(pos))
    # Successfully enumerating native positions and not finding the target is
    # proof that the target quantity is zero.
    return True, total if observed else 0.0


def _query_order(broker: Any, order_id: str, symbol: str = "") -> Mapping[str, Any]:
    if not order_id:
        return {}
    attempts = (
        ("get_order_status", ((order_id,), {"order_id": order_id})),
        ("get_order", ((order_id,), {"order_id": order_id})),
        ("get_order_by_id", ((order_id,), {"order_id": order_id})),
        ("fetch_order", ((order_id,), {"order_id": order_id, "symbol": symbol})),
        ("query_order", ((order_id,), {"order_id": order_id, "symbol": symbol})),
    )
    for method_name, (positional, keywords) in attempts:
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        for call_args, call_kwargs in ((positional, {}), ((), keywords)):
            try:
                result = method(*call_args, **call_kwargs)
                if isinstance(result, Mapping):
                    return result
            except TypeError:
                continue
            except Exception:
                break
    # Common Kraken low-level fallback retained without making Kraken special in
    # the main state machine.
    private = getattr(broker, "_kraken_api_call", None)
    if callable(private):
        try:
            result = private("QueryOrders", {"txid": order_id, "trades": True})
            if isinstance(result, Mapping):
                nested = result.get("result")
                if isinstance(nested, Mapping):
                    row = nested.get(order_id)
                    if isinstance(row, Mapping):
                        return row
                return result
        except Exception:
            pass
    return {}


def _submit_exit_once(universal: ModuleType, broker: Any, pos: dict[str, Any], market: float) -> dict[str, Any]:
    symbol = universal.auto_exit._sym(pos.get("symbol"))
    qty = universal.auto_exit._quantity(pos)
    if qty <= 0.0:
        return {"status": "error", "error": "invalid_position_quantity"}
    close_side = "sell" if universal.auto_exit._side(pos.get("side"), pos) in {"long", "buy"} else "buy"
    calls = (
        ("place_market_order", {"symbol": symbol, "side": close_side, "size": qty}),
        ("place_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty}),
        ("market_order", {"symbol": symbol, "side": close_side, "quantity": qty}),
        ("execute_order", {"symbol": symbol, "side": close_side, "order_type": "market", "quantity": qty, "reduce_only": True}),
    )
    errors: list[str] = []
    for method_name, kwargs in calls:
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            result = method(**kwargs)
        except TypeError:
            try:
                result = method(symbol, close_side, qty)
            except Exception as exc:
                errors.append(f"{method_name}:{type(exc).__name__}:{exc}")
                continue
        except Exception as exc:
            errors.append(f"{method_name}:{type(exc).__name__}:{exc}")
            continue

        payload = dict(result) if isinstance(result, Mapping) else {
            "status": "unknown",
            "raw": str(result),
        }
        payload.setdefault("submission_method", method_name)
        if _is_full_fill(payload, qty) or _is_submission_ack(payload):
            # Crucially: once a venue acknowledges a submission, do NOT fall
            # through to another method and risk submitting a duplicate close.
            return payload
        if _is_terminal_failure(payload):
            errors.append(f"{method_name}:{_status(payload)}:{payload.get('error', '')}")
            continue
        # Ambiguous transport/application response: preserve it as unknown and
        # reconcile instead of calling another submit method.
        if _order_id(payload) or payload:
            payload.setdefault("status", "unknown")
            return payload
    return {"status": "error", "error": "exit_submission_failed", "details": errors[-4:]}


def _pending_key(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> tuple[int, str, str]:
    symbol = universal.auto_exit._sym(pos.get("symbol"))
    pid = str(pos.get("position_id") or symbol)
    return id(broker), pid, symbol


def _confirm_by_position(universal: ModuleType, broker: Any, pending: Mapping[str, Any]) -> bool:
    observed, current_qty = _position_quantity_for_symbol(
        universal,
        broker,
        str(pending.get("symbol") or ""),
    )
    if not observed:
        return False
    before = max(0.0, _f(pending.get("quantity")))
    if before <= 0.0:
        return current_qty <= 0.0
    return current_qty <= max(1e-12, before * 0.001)


def _reconcile_pending(universal: ModuleType, broker: Any, pending: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    order_id = str(pending.get("order_id") or "")
    payload = _query_order(broker, order_id, str(pending.get("symbol") or "")) if order_id else {}
    expected = max(0.0, _f(pending.get("quantity")))
    if _is_full_fill(payload, expected):
        return "filled", payload
    if _confirm_by_position(universal, broker, pending):
        return "filled", payload
    if _is_terminal_failure(payload):
        return "failed", payload
    return "pending", payload


def _discover_brokers(universal: ModuleType) -> list[Any]:
    """Discover broker instances from canonical registries by capability."""
    candidates: list[Any] = []
    seen: set[int] = set()

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, Mapping):
            for nested in value.values():
                add(nested)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for nested in value:
                add(nested)
            return
        oid = id(value)
        if oid in seen:
            return
        has_positions = any(callable(getattr(value, name, None)) for name in ("get_positions", "list_positions", "get_open_positions")) or getattr(value, "position_tracker", None) is not None
        has_order = any(callable(getattr(value, name, None)) for name in ("place_market_order", "place_order", "market_order", "execute_order"))
        if has_positions and has_order:
            seen.add(oid)
            candidates.append(value)

    for name in ("bot.broker_manager", "broker_manager", "bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        for attr in (
            "GLOBAL_PLATFORM_BROKERS", "_PLATFORM_BROKER_INSTANCES", "platform_brokers",
            "_platform_brokers", "user_brokers", "_user_brokers", "brokers", "_brokers",
            "multi_account_broker_manager", "manager", "broker_manager",
        ):
            try:
                add(getattr(module, attr, None))
            except Exception:
                pass
        for getter_name in ("get_multi_account_broker_manager", "get_broker_manager"):
            getter = getattr(module, getter_name, None)
            if callable(getter):
                try:
                    manager = getter()
                except Exception:
                    continue
                for attr in ("platform_brokers", "_platform_brokers", "user_brokers", "_user_brokers", "brokers", "_brokers"):
                    add(getattr(manager, attr, None))

    for broker in candidates:
        try:
            universal._register_broker(broker)
        except Exception:
            pass
    return candidates


def _safe_scan_broker(universal: ModuleType, broker: Any) -> int:
    closed = 0
    account = universal._account_label(broker)
    venue = universal.auto_exit._broker_label(broker) or "unknown"
    for pos in universal._tracker_positions(broker):
        symbol = universal.auto_exit._sym(pos.get("symbol"))
        pid = str(pos.get("position_id") or symbol)
        key = _pending_key(universal, broker, pos)

        with _PENDING_LOCK:
            pending = dict(_PENDING.get(key) or {})
        if pending:
            state, proof = _reconcile_pending(universal, broker, pending)
            if state == "filled":
                fill_payload = dict(proof or {})
                fill_payload.setdefault("order_id", pending.get("order_id", ""))
                fill_payload.setdefault("filled_price", pending.get("market", 0.0))
                universal._mark_closed(
                    broker,
                    pos,
                    fill_payload,
                    str(pending.get("reason") or "exit"),
                    _filled_price(fill_payload, _f(pending.get("market"))),
                )
                universal.auto_exit._HIGH_WATER.pop(universal.auto_exit._position_key(pos), None)
                with _PENDING_LOCK:
                    _PENDING.pop(key, None)
                closed += 1
                LOGGER.critical(
                    "UNIVERSAL_EXIT_V67_CONFIRMED marker=%s venue=%s account=%s symbol=%s "
                    "order_id=%s status=%s fill_or_position_proof=true",
                    MARKER, venue, account, symbol, pending.get("order_id", ""), _status(proof) or "position_reduction",
                )
                continue
            if state == "failed":
                with _PENDING_LOCK:
                    _PENDING.pop(key, None)
                LOGGER.error(
                    "UNIVERSAL_EXIT_V67_TERMINAL_FAILURE marker=%s venue=%s account=%s symbol=%s "
                    "order_id=%s status=%s tracker_preserved=true",
                    MARKER, venue, account, symbol, pending.get("order_id", ""), _status(proof),
                )
                continue
            age = max(0.0, time.time() - _f(pending.get("submitted_at"), time.time()))
            LOGGER.warning(
                "UNIVERSAL_EXIT_V67_PENDING marker=%s venue=%s account=%s symbol=%s order_id=%s "
                "age_s=%.1f duplicate_submit_blocked=true tracker_preserved=true",
                MARKER, venue, account, symbol, pending.get("order_id", ""), age,
            )
            continue

        entry = universal.auto_exit._entry_price(pos)
        qty = universal.auto_exit._quantity(pos)
        if not symbol or entry <= 0.0 or qty <= 0.0:
            continue
        market = universal.auto_exit._price(broker, symbol)
        if market <= 0.0:
            continue
        hit, reason, target = universal._trigger(broker, pos, market)
        if not hit:
            continue

        # A deterministic below-minimum rejection cannot become executable a
        # few seconds later.  Re-evaluate periodically so a deposit, conversion,
        # or venue-rule refresh can recover it without hammering private APIs.
        now = time.time()
        with _PENDING_LOCK:
            retry_after = _RETRY_AFTER.get(key, 0.0)
            if retry_after and retry_after <= now:
                _RETRY_AFTER.pop(key, None)
                retry_after = 0.0
        if retry_after > now:
            continue

        active_key = f"{id(broker)}:{pid}:{symbol}"
        if active_key in universal._ACTIVE:
            continue
        universal._ACTIVE.add(active_key)
        try:
            LOGGER.critical(
                "UNIVERSAL_EXIT_V67_TRIGGER marker=%s venue=%s account=%s symbol=%s reason=%s "
                "target=%.8f market=%.8f entry=%.8f qty=%.8f",
                MARKER, venue, account, symbol, reason, target, market, entry, qty,
            )
            result = _submit_exit_once(universal, broker, pos, market)
            if _is_full_fill(result, qty) or _confirm_by_position(
                universal,
                broker,
                {"symbol": symbol, "quantity": qty},
            ):
                universal._mark_closed(broker, pos, result, reason, _filled_price(result, market))
                universal.auto_exit._HIGH_WATER.pop(universal.auto_exit._position_key(pos), None)
                closed += 1
                LOGGER.critical(
                    "UNIVERSAL_EXIT_V67_CONFIRMED_IMMEDIATE marker=%s venue=%s account=%s symbol=%s "
                    "order_id=%s status=%s",
                    MARKER, venue, account, symbol, _order_id(result), _status(result) or "position_reduction",
                )
                continue
            if _is_terminal_failure(result):
                cooldown_s = _terminal_retry_cooldown_s(result)
                if cooldown_s > 0.0:
                    with _PENDING_LOCK:
                        _RETRY_AFTER[key] = time.time() + cooldown_s
                    LOGGER.error(
                        "UNIVERSAL_EXIT_V67_NON_EXECUTABLE_QUARANTINED marker=%s venue=%s account=%s "
                        "symbol=%s status=%s error=%s retry_after_s=%.0f tracker_preserved=true "
                        "quantity_increased=false short_created=false",
                        MARKER, venue, account, symbol, _status(result),
                        result.get("error", result), cooldown_s,
                    )
                else:
                    LOGGER.error(
                        "UNIVERSAL_EXIT_V67_SUBMISSION_REJECTED marker=%s venue=%s account=%s symbol=%s status=%s error=%s",
                        MARKER, venue, account, symbol, _status(result), result.get("error", result),
                    )
                continue

            with _PENDING_LOCK:
                _PENDING[key] = {
                    "order_id": _order_id(result),
                    "submitted_at": time.time(),
                    "quantity": qty,
                    "symbol": symbol,
                    "reason": reason,
                    "market": market,
                    "submission_status": _status(result) or "unknown",
                }
            LOGGER.critical(
                "UNIVERSAL_EXIT_V67_ACCEPTED_PENDING marker=%s venue=%s account=%s symbol=%s "
                "order_id=%s status=%s tracker_preserved=true duplicate_submit_blocked=true",
                MARKER, venue, account, symbol, _order_id(result), _status(result) or "unknown",
            )
        finally:
            universal._ACTIVE.discard(active_key)
    return closed


def _patch_universal(module: ModuleType) -> bool:
    current = getattr(module, "_scan_broker", None)
    if not callable(current):
        return False
    if getattr(current, _PATCHED_ATTR, False):
        return True

    def safe_scan(broker: Any) -> int:
        _discover_brokers(module)
        return _safe_scan_broker(module, broker)

    setattr(safe_scan, _PATCHED_ATTR, True)
    setattr(safe_scan, "__wrapped__", current)
    module._scan_broker = safe_scan

    snapshot = getattr(module, "_snapshot", None)
    if callable(snapshot) and not getattr(snapshot, _PATCHED_ATTR, False):
        @wraps(snapshot)
        def snapshot_with_discovery():
            _discover_brokers(module)
            return snapshot()
        setattr(snapshot_with_discovery, _PATCHED_ATTR, True)
        module._snapshot = snapshot_with_discovery

    LOGGER.critical(
        "UNIVERSAL_EXIT_FILL_RECONCILIATION_V67_PATCHED marker=%s module=%s "
        "accepted_is_fill=false generic_registry_discovery=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_auto_exit(module: ModuleType) -> bool:
    current_scan = getattr(module, "_scan_once", None)
    if not callable(current_scan) or getattr(current_scan, _PATCHED_ATTR, False):
        return bool(callable(current_scan))

    @wraps(current_scan)
    def delegated_scan(engine: Any) -> int:
        global _LAST_DELEGATE_LOG
        if str(os.environ.get("NIJA_UNIVERSAL_BROKER_EXIT_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on", "enabled"}:
            now = time.monotonic()
            if now - _LAST_DELEGATE_LOG > 60.0:
                _LAST_DELEGATE_LOG = now
                LOGGER.info(
                    "AUTO_EXIT_V67_DELEGATED marker=%s reason=single_universal_exit_authority duplicate_exit_prevention=true",
                    MARKER,
                )
            return 0
        return current_scan(engine)

    setattr(delegated_scan, _PATCHED_ATTR, True)
    module._scan_once = delegated_scan
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.universal_broker_exit_supervisor_patch", "universal_broker_exit_supervisor_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_universal(module) or changed
    for name in ("bot.auto_exit_sl_tp_runtime_patch", "auto_exit_sl_tp_runtime_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_auto_exit(module) or changed
    return changed


def install_import_hook() -> bool:
    with _INSTALL_LOCK:
        try:
            importlib.import_module("bot.universal_broker_exit_supervisor_patch")
        except Exception:
            pass
        try:
            importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
        except Exception:
            pass
        _patch_loaded()
        flag = "_NIJA_UNIVERSAL_EXIT_FILL_RECONCILIATION_V67_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "universal_broker_exit" in str(name) or "auto_exit_sl_tp" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_UNIVERSAL_EXIT_FILL_RECONCILIATION_V67_INSTALLED"] = "1"
        LOGGER.critical(
            "UNIVERSAL_EXIT_FILL_RECONCILIATION_V67_INSTALLED marker=%s fill_confirmation_required=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_status", "_order_id",
    "_filled_quantity", "_is_full_fill", "_is_submission_ack", "_query_order",
]
