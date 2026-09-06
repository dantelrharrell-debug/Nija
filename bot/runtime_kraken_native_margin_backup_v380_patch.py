"""Kraken native fixed SL/TP backup for authenticated margin positions v380.

Supplement NIJA's v371 software SL/TP/TSL/TTP monitor with exchange-side fixed
stop-loss and take-profit orders. Trailing protection remains software-owned.

Safety invariants:
* only authenticated OpenPositions exposure is eligible;
* only existing long margin exposure is handled by this release;
* every native order is SELL + reduce_only and carries position leverage;
* current price must be strictly between stop and TP before arming;
* OpenOrders is checked before and after AddOrder; ACK/txid alone is not proof;
* stop is armed before take-profit;
* deterministic Kraken cl_ord_id values make the armer idempotent and allow
  stale NIJA-native orders to be cancelled after matching margin exposure ends;
* private calls preserve canonical writer/nonce/rate/fencing authority;
* no exposure, fill, execution readiness, or profit is fabricated.
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import math
import os
import threading
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_native_margin_backup_v380")
MARKER = "20260906-kraken-native-margin-backup-v380"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_NATIVE_MARGIN_BACKUP_V380_READY"
_INSTALLED_FLAG = "NIJA_RUNTIME_KRAKEN_NATIVE_MARGIN_BACKUP_V380_INSTALLED"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LAST_SIGNATURE = ""
_EPS = 1e-12
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_PREFIX_SL = "njsl"
_PREFIX_TP = "njtp"


def _truthy(value: Any, default: str = "true") -> bool:
    raw = default if value is None else value
    return str(raw or "").strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def _poll_s() -> float:
    try:
        return max(5.0, min(60.0, float(os.environ.get("NIJA_KRAKEN_NATIVE_MARGIN_BACKUP_POLL_S", "15") or 15.0)))
    except Exception:
        return 15.0


def _v366():
    return importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")


def _v367():
    return importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")


def _v371():
    return importlib.import_module("bot.runtime_kraken_margin_full_protection_v371_patch")


def _kraken_exit():
    return importlib.import_module("bot.kraken_all_account_exit_runtime_patch")


def _private_call(broker: Any):
    try:
        return getattr(_v366(), "_private_call")(broker)
    except Exception:
        return None


def _category(name: str) -> Any:
    try:
        profiles = importlib.import_module("bot.kraken_rate_profiles")
        enum = getattr(profiles, "KrakenAPICategory", None)
        return getattr(enum, name, None) if enum is not None else None
    except Exception:
        return None


def _call(broker: Any, method: str, params: dict[str, Any], category_name: str) -> Any:
    call = _private_call(broker)
    if not callable(call):
        raise RuntimeError("kraken_private_api_unavailable")
    category = _category(category_name)
    return call(method, params, category=category) if category is not None else call(method, params)


def _native_truth(account: str, broker: Any) -> tuple[bool, dict[str, dict[str, Any]], str]:
    v367 = _v367()
    cache = getattr(v367, "_NATIVE_CACHE", None)
    if isinstance(cache, dict):
        cache.pop(str(account), None)
    probe = getattr(v367, "_native_protection", None)
    if not callable(probe):
        return False, {}, "v367_native_probe_unavailable"
    ok, rows, reason = probe(str(account), broker)
    return bool(ok), {str(key): dict(value) for key, value in dict(rows or {}).items()}, str(reason or "")


def _pair_and_price(broker: Any, symbol: str) -> tuple[str, float]:
    module = _kraken_exit()
    resolver = getattr(module, "_resolve_pair", None)
    price_fn = getattr(module, "_ticker_price", None)
    if not callable(resolver) or not callable(price_fn):
        return "", 0.0
    pair = str(resolver(broker, symbol) or "").strip()
    return (pair, max(0.0, _f(price_fn(broker, pair)))) if pair else ("", 0.0)


def _fmt(value: float) -> str:
    text = f"{float(value):.12f}".rstrip("0").rstrip(".")
    return text or "0"


def _client_id(account: str, symbol: str, leg: str) -> str:
    digest = hashlib.sha1(f"{account}|{symbol}".encode("utf-8")).hexdigest()[:12]
    prefix = _PREFIX_SL if leg == "stop-loss" else _PREFIX_TP
    return f"{prefix}{digest}"[:18]


def _submit_reduce_only(
    broker: Any,
    *,
    pair: str,
    quantity: float,
    leverage: int,
    ordertype: str,
    trigger: float,
    client_id: str = "",
) -> tuple[bool, tuple[str, ...], str]:
    params: dict[str, Any] = {
        "pair": pair,
        "type": "sell",
        "ordertype": ordertype,
        "volume": _fmt(quantity),
        "price": _fmt(trigger),
        "reduce_only": True,
    }
    if leverage > 1:
        params["leverage"] = str(leverage)
    if client_id:
        params["cl_ord_id"] = str(client_id)[:18]
    try:
        payload = _call(broker, "AddOrder", params, "EXIT")
    except Exception as exc:
        return False, (), f"addorder_exception:{type(exc).__name__}:{exc}"
    if not isinstance(payload, Mapping):
        return False, (), "invalid_addorder_payload"
    errors = payload.get("error") or []
    if isinstance(errors, str):
        errors = [errors]
    if errors:
        return False, (), "addorder_rejected:" + ",".join(str(item) for item in errors)
    result = payload.get("result") or {}
    if not isinstance(result, Mapping):
        return False, (), "invalid_addorder_result"
    txids = result.get("txid") or ()
    if isinstance(txids, str):
        txids = (txids,)
    txids = tuple(str(item) for item in tuple(txids or ()) if str(item))
    if not txids:
        return False, (), "addorder_ack_without_txid"
    return True, txids, "ok"


def _row_targets(raw: Mapping[str, Any]) -> dict[str, Any]:
    fn = getattr(_v371(), "_ensure_software_targets", None)
    row = fn(dict(raw)) if callable(fn) else dict(raw)
    return dict(row) if isinstance(row, Mapping) else dict(raw)


def _arm_position(account: str, broker: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    row = _row_targets(raw)
    symbol = str(_v366().canonical_symbol(row.get("symbol")) or "").strip()
    quantity = max(0.0, _f(row.get("remaining_units", row.get("quantity"))))
    entry = max(0.0, _f(row.get("entry_price", row.get("avg_entry_price"))))
    stop = max(0.0, _f(row.get("stop_loss")))
    tp = max(0.0, _f(row.get("take_profit_1", row.get("take_profit"))))
    leverage = max(1, min(5, int(_f(row.get("leverage"), 1.0) or 1.0)))
    ids = tuple(str(item) for item in tuple(row.get("position_ids", ()) or ()) if str(item))
    base = {
        "account": account, "symbol": symbol, "quantity": quantity, "entry": entry,
        "stop": stop, "take_profit": tp, "leverage": leverage, "position_ids": ids,
        "stop_armed": False, "take_profit_armed": False,
        "native_backup_verified": False, "submitted": (),
    }
    if not symbol or quantity <= _EPS or entry <= _EPS or not ids:
        return {**base, "reason": "position_identity_unproven"}
    if str(row.get("side") or "long").strip().lower() not in {"long", "buy"}:
        return {**base, "reason": "short_native_backup_not_enabled_v380"}
    if stop <= _EPS or tp <= _EPS or not (stop < entry < tp):
        return {**base, "reason": "protective_targets_invalid"}

    pair, current = _pair_and_price(broker, symbol)
    base.update({"pair": pair, "current_price": current})
    if not pair or current <= _EPS:
        return {**base, "reason": "current_price_or_pair_unproven"}
    if not (stop < current < tp):
        return {**base, "reason": "trigger_already_crossed_software_exit_owns_due_action"}

    native_ok, native_rows, native_reason = _native_truth(account, broker)
    if not native_ok:
        return {**base, "reason": f"openorders_unproven:{native_reason}"}
    native = native_rows.get(symbol, {})
    tolerance = max(_EPS, quantity * 0.005)
    stop_armed = max(0.0, _f(native.get("stop_qty"))) + tolerance >= quantity
    tp_armed = max(0.0, _f(native.get("take_profit_qty"))) + tolerance >= quantity
    submitted: list[tuple[str, tuple[str, ...]]] = []

    if not stop_armed:
        ok, txids, reason = _submit_reduce_only(
            broker, pair=pair, quantity=quantity, leverage=leverage,
            ordertype="stop-loss", trigger=stop,
            client_id=_client_id(account, symbol, "stop-loss"),
        )
        if not ok:
            return {**base, "take_profit_armed": tp_armed, "reason": f"stop_submit_failed:{reason}"}
        submitted.append(("stop-loss", txids))
        native_ok, native_rows, native_reason = _native_truth(account, broker)
        native = native_rows.get(symbol, {}) if native_ok else {}
        stop_armed = bool(native_ok and max(0.0, _f(native.get("stop_qty"))) + tolerance >= quantity)
        if not stop_armed:
            return {**base, "submitted": tuple(submitted), "reason": f"stop_post_submit_proof_failed:{native_reason}"}

    if not tp_armed:
        ok, txids, reason = _submit_reduce_only(
            broker, pair=pair, quantity=quantity, leverage=leverage,
            ordertype="take-profit", trigger=tp,
            client_id=_client_id(account, symbol, "take-profit"),
        )
        if not ok:
            return {
                **base, "stop_armed": stop_armed, "submitted": tuple(submitted),
                "reason": f"take_profit_submit_failed:{reason}",
            }
        submitted.append(("take-profit", txids))

    native_ok, native_rows, native_reason = _native_truth(account, broker)
    native = native_rows.get(symbol, {}) if native_ok else {}
    stop_armed = bool(native_ok and max(0.0, _f(native.get("stop_qty"))) + tolerance >= quantity)
    tp_armed = bool(native_ok and max(0.0, _f(native.get("take_profit_qty"))) + tolerance >= quantity)
    verified = bool(stop_armed and tp_armed)
    return {
        **base, "stop_armed": stop_armed, "take_profit_armed": tp_armed,
        "native_backup_verified": verified, "submitted": tuple(submitted),
        "reason": "ok" if verified else f"post_submit_openorders_unproven:{native_reason}",
    }


def _cleanup_orphans(account: str, broker: Any, active_symbols: set[str]) -> tuple[str, ...]:
    """Cancel only v380-tagged orders whose authenticated margin symbol is absent."""
    try:
        payload = _call(broker, "OpenOrders", {"trades": "false"}, "QUERY")
    except Exception:
        return ()
    if not isinstance(payload, Mapping) or payload.get("error"):
        return ()
    result = payload.get("result") or {}
    opened = result.get("open", result) if isinstance(result, Mapping) else {}
    if not isinstance(opened, Mapping):
        return ()
    cancelled: list[str] = []
    for order_id, raw in opened.items():
        if not isinstance(raw, Mapping):
            continue
        client_id = str(raw.get("cl_ord_id") or raw.get("cl_ordid") or "").strip()
        if not client_id.startswith((_PREFIX_SL, _PREFIX_TP)):
            continue
        descr = raw.get("descr") if isinstance(raw.get("descr"), Mapping) else {}
        symbol = str(_v366().canonical_symbol(descr.get("pair") or raw.get("pair")) or "")
        if not symbol or symbol in active_symbols:
            continue
        if client_id not in {
            _client_id(account, symbol, "stop-loss"),
            _client_id(account, symbol, "take-profit"),
        }:
            continue
        try:
            response = _call(broker, "CancelOrder", {"txid": str(order_id)}, "EXIT")
        except Exception:
            continue
        if isinstance(response, Mapping) and not (response.get("error") or []):
            cancelled.append(str(order_id))
    if cancelled:
        LOGGER.critical(
            "KRAKEN_NATIVE_MARGIN_BACKUP_V380_ORPHANS_CANCELLED marker=%s account=%s order_ids=%s "
            "client_tag_match=true exposure_absent=true unrelated_orders_untouched=true safety_gates_bypassed=false",
            MARKER, account, tuple(cancelled),
        )
    return tuple(cancelled)


def reconcile_once() -> dict[str, Any]:
    if not _truthy(os.environ.get("NIJA_KRAKEN_NATIVE_MARGIN_BACKUP_ENABLED", "true")):
        os.environ[_READY_FLAG] = "0"
        return {"ready": False, "enabled": False, "accounts": {}, "reason": "disabled"}
    brokers_fn = getattr(_v367(), "_account_brokers", None)
    if not callable(brokers_fn):
        return {"ready": False, "enabled": True, "accounts": {}, "reason": "account_brokers_unavailable"}

    account_results: dict[str, Any] = {}
    any_margin = False
    all_margin_verified = True
    for account, broker in list(brokers_fn() or []):
        try:
            ok, positions, reason = _v366().fetch_margin_positions(broker, account=account, force=True)
        except Exception as exc:
            ok, positions, reason = False, {}, f"openpositions_exception:{type(exc).__name__}:{exc}"
        if not ok:
            account_results[str(account)] = {"ready": False, "positions": (), "reason": reason}
            all_margin_verified = False
            continue
        active_symbols = {str(_v366().canonical_symbol(symbol) or "") for symbol in dict(positions or {})}
        cancelled = _cleanup_orphans(str(account), broker, active_symbols)
        proofs = []
        for raw in dict(positions or {}).values():
            any_margin = True
            proof = _arm_position(str(account), broker, raw)
            proofs.append(proof)
            all_margin_verified = bool(all_margin_verified and proof.get("native_backup_verified"))
        account_results[str(account)] = {
            "ready": all(bool(item.get("native_backup_verified")) for item in proofs) if proofs else True,
            "positions": tuple(proofs), "cancelled_orphans": cancelled,
            "reason": "ok" if proofs else "no_open_margin_positions",
        }

    ready = bool(all_margin_verified)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    return {"ready": ready, "enabled": True, "any_margin": any_margin, "accounts": account_results}


def audit_once() -> dict[str, Any]:
    global _LAST_SIGNATURE
    try:
        result = reconcile_once()
    except Exception as exc:
        result = {"ready": False, "enabled": True, "accounts": {}, "error": f"{type(exc).__name__}:{exc}"}
        os.environ[_READY_FLAG] = "0"
    signature = repr(result)
    with _LOCK:
        changed = signature != _LAST_SIGNATURE
        if changed:
            _LAST_SIGNATURE = signature
    if changed:
        log = LOGGER.critical if result.get("ready") else LOGGER.warning
        log(
            "KRAKEN_NATIVE_MARGIN_BACKUP_V380_%s marker=%s state=%s "
            "native_fixed_stop_loss=true native_fixed_take_profit=true software_tsl_ttp_unchanged=true "
            "reduce_only_required=true authenticated_openpositions_required=true openorders_post_submit_proof_required=true "
            "client_order_id_idempotency=true orphan_cleanup=true ack_not_protection_proof=true "
            "forced_trade=false new_exposure=false safety_gates_bypassed=false",
            "READY" if result.get("ready") else "PENDING", MARKER, result,
        )
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        wake = getattr(v281, "audit_once", None)
        if callable(wake):
            wake()
    except Exception:
        pass
    return result


def _worker() -> None:
    while not _STOP.wait(_poll_s()):
        try:
            audit_once()
        except Exception:
            LOGGER.debug("v380 native-backup pulse failed", exc_info=True)


def install_import_hook() -> bool:
    global _THREAD
    os.environ.setdefault("NIJA_KRAKEN_NATIVE_MARGIN_BACKUP_ENABLED", "true")
    os.environ.setdefault("NIJA_KRAKEN_NATIVE_MARGIN_BACKUP_POLL_S", "15")
    os.environ[_INSTALLED_FLAG] = "1"
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()
            _THREAD = threading.Thread(target=_worker, name="KrakenNativeMarginBackupV380", daemon=True)
            _THREAD.start()
    audit_once()
    LOGGER.critical(
        "RUNTIME_KRAKEN_NATIVE_MARGIN_BACKUP_V380_INSTALLED marker=%s enabled=%s monitor_alive=%s "
        "native_fixed_only=true trailing_remains_software=true reduce_only=true client_id_idempotency=true "
        "orphan_cleanup=true safety_gates_bypassed=false",
        MARKER,
        str(_truthy(os.environ.get("NIJA_KRAKEN_NATIVE_MARGIN_BACKUP_ENABLED", "true"))).lower(),
        str(bool(_THREAD and _THREAD.is_alive())).lower(),
    )
    return bool(_THREAD and _THREAD.is_alive())


def install() -> bool:
    return install_import_hook()


def stop() -> None:
    _STOP.set()


__all__ = [
    "MARKER", "install", "install_import_hook", "audit_once", "reconcile_once", "stop",
    "_client_id", "_submit_reduce_only", "_arm_position", "_cleanup_orphans",
]
