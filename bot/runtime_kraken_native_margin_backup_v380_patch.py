"""Kraken native fixed SL/TP backup for authenticated margin positions v380.

This is a supplemental exchange-side safety layer above NIJA's existing v371
software SL/TP/TSL/TTP monitor.  It arms only fixed stop-loss and fixed
 take-profit orders at Kraken; trailing stop-loss and trailing take-profit remain
under the already-verified NIJA software monitor.

Safety invariants:
* only broker-authenticated OpenPositions rows are eligible;
* only existing long margin exposure is handled by this release;
* every order is SELL + reduce_only and carries the position leverage;
* current price must be strictly between the stop and TP trigger, so a stale
  conditional order is never used instead of an already-due software exit;
* OpenOrders is checked before every submit and again after submit; an AddOrder
  acknowledgement alone is never promoted to native protection proof;
* stop is armed before take-profit so partial hardening always prioritises loss
  containment;
* private AddOrder travels through the canonical Kraken private-call boundary,
  preserving writer/nonce/rate/fencing authority;
* no new exposure, forced trade, fill, or profit is fabricated.

Kraken reduce_only guarantees these protective orders cannot increase or open a
position after the margin exposure has been reduced/closed.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
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


def _native_truth(account: str, broker: Any) -> tuple[bool, dict[str, dict[str, Any]], str]:
    v367 = _v367()
    try:
        cache = getattr(v367, "_NATIVE_CACHE", None)
        if isinstance(cache, dict):
            cache.pop(str(account), None)
    except Exception:
        pass
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
    if not pair:
        return "", 0.0
    return pair, max(0.0, _f(price_fn(broker, pair)))


def _fmt(value: float) -> str:
    text = f"{float(value):.12f}".rstrip("0").rstrip(".")
    return text or "0"


def _submit_reduce_only(
    broker: Any,
    *,
    pair: str,
    quantity: float,
    leverage: int,
    ordertype: str,
    trigger: float,
) -> tuple[bool, tuple[str, ...], str]:
    call = _private_call(broker)
    if not callable(call):
        return False, (), "kraken_private_api_unavailable"
    params = {
        "pair": pair,
        "type": "sell",
        "ordertype": ordertype,
        "volume": _fmt(quantity),
        "price": _fmt(trigger),
        "reduce_only": True,
    }
    if leverage > 1:
        params["leverage"] = str(leverage)
    try:
        category = None
        try:
            profiles = importlib.import_module("bot.kraken_rate_profiles")
            enum = getattr(profiles, "KrakenAPICategory", None)
            category = getattr(enum, "EXIT", None) if enum is not None else None
        except Exception:
            category = None
        payload = call("AddOrder", params, category=category) if category is not None else call("AddOrder", params)
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
    v366 = _v366()
    row = _row_targets(raw)
    symbol = str(v366.canonical_symbol(row.get("symbol")) or "").strip()
    quantity = max(0.0, _f(row.get("remaining_units", row.get("quantity"))))
    entry = max(0.0, _f(row.get("entry_price", row.get("avg_entry_price"))))
    stop = max(0.0, _f(row.get("stop_loss")))
    tp = max(0.0, _f(row.get("take_profit_1", row.get("take_profit"))))
    leverage = max(1, min(5, int(_f(row.get("leverage"), 1.0) or 1.0)))
    ids = tuple(str(item) for item in tuple(row.get("position_ids", ()) or ()) if str(item))
    base = {
        "account": account,
        "symbol": symbol,
        "quantity": quantity,
        "entry": entry,
        "stop": stop,
        "take_profit": tp,
        "leverage": leverage,
        "position_ids": ids,
        "stop_armed": False,
        "take_profit_armed": False,
        "native_backup_verified": False,
        "submitted": (),
    }
    if not symbol or quantity <= _EPS or entry <= _EPS or not ids:
        return {**base, "reason": "position_identity_unproven"}
    if str(row.get("side") or "long").strip().lower() not in {"long", "buy"}:
        return {**base, "reason": "short_native_backup_not_enabled_v380"}
    if stop <= _EPS or tp <= _EPS or not (stop < entry < tp):
        return {**base, "reason": "protective_targets_invalid"}

    pair, current = _pair_and_price(broker, symbol)
    base["pair"] = pair
    base["current_price"] = current
    if not pair or current <= _EPS:
        return {**base, "reason": "current_price_or_pair_unproven"}
    if not (stop < current < tp):
        # A target is already due.  Do not park a stale conditional order; the
        # existing v367 software monitor owns the immediate exit decision.
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
        )
        if not ok:
            return {**base, "stop_armed": False, "take_profit_armed": tp_armed, "reason": f"stop_submit_failed:{reason}"}
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
        )
        if not ok:
            return {
                **base, "stop_armed": stop_armed, "take_profit_armed": False,
                "submitted": tuple(submitted), "reason": f"take_profit_submit_failed:{reason}",
            }
        submitted.append(("take-profit", txids))

    native_ok, native_rows, native_reason = _native_truth(account, broker)
    native = native_rows.get(symbol, {}) if native_ok else {}
    stop_armed = bool(native_ok and max(0.0, _f(native.get("stop_qty"))) + tolerance >= quantity)
    tp_armed = bool(native_ok and max(0.0, _f(native.get("take_profit_qty"))) + tolerance >= quantity)
    verified = bool(stop_armed and tp_armed)
    return {
        **base,
        "stop_armed": stop_armed,
        "take_profit_armed": tp_armed,
        "native_backup_verified": verified,
        "submitted": tuple(submitted),
        "reason": "ok" if verified else f"post_submit_openorders_unproven:{native_reason}",
    }


def reconcile_once() -> dict[str, Any]:
    if not _truthy(os.environ.get("NIJA_KRAKEN_NATIVE_MARGIN_BACKUP_ENABLED", "true")):
        os.environ[_READY_FLAG] = "0"
        return {"ready": False, "enabled": False, "accounts": {}, "reason": "disabled"}
    v366 = _v366()
    v367 = _v367()
    brokers_fn = getattr(v367, "_account_brokers", None)
    if not callable(brokers_fn):
        return {"ready": False, "enabled": True, "accounts": {}, "reason": "account_brokers_unavailable"}

    account_results: dict[str, Any] = {}
    any_margin = False
    all_margin_verified = True
    for account, broker in list(brokers_fn() or []):
        try:
            ok, positions, reason = v366.fetch_margin_positions(broker, account=account, force=True)
        except Exception as exc:
            ok, positions, reason = False, {}, f"openpositions_exception:{type(exc).__name__}:{exc}"
        if not ok:
            account_results[str(account)] = {"ready": False, "positions": (), "reason": reason}
            # Unproven read cannot be treated as no exposure.
            all_margin_verified = False
            continue
        position_results = []
        for raw in dict(positions or {}).values():
            any_margin = True
            proof = _arm_position(str(account), broker, raw)
            position_results.append(proof)
            all_margin_verified = bool(all_margin_verified and proof.get("native_backup_verified"))
        account_results[str(account)] = {
            "ready": all(bool(item.get("native_backup_verified")) for item in position_results) if position_results else True,
            "positions": tuple(position_results),
            "reason": "ok" if position_results else "no_open_margin_positions",
        }

    # Ready means every authenticated Kraken margin exposure observed this cycle
    # has exchange-verified native fixed SL+TP.  No-margin is a safe idle state.
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
            "ack_not_protection_proof=true forced_trade=false new_exposure=false safety_gates_bypassed=false",
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
    # Do one immediate pass after the worker is alive.  Failures leave software
    # protection intact and the native readiness flag false; they never bypass
    # the canonical private-call safety boundary.
    audit_once()
    LOGGER.critical(
        "RUNTIME_KRAKEN_NATIVE_MARGIN_BACKUP_V380_INSTALLED marker=%s enabled=%s monitor_alive=%s "
        "native_fixed_only=true trailing_remains_software=true reduce_only=true safety_gates_bypassed=false",
        MARKER,
        str(_truthy(os.environ.get("NIJA_KRAKEN_NATIVE_MARGIN_BACKUP_ENABLED", "true"))).lower(),
        str(bool(_THREAD and _THREAD.is_alive())).lower(),
    )
    return bool(_THREAD and _THREAD.is_alive())


def install() -> bool:
    return install_import_hook()


def stop() -> None:
    _STOP.set()


__all__ = ["MARKER", "install", "install_import_hook", "audit_once", "reconcile_once", "stop"]
