"""Capture genuine Kraken AddOrder txids before outer ACK timeout (v369).

The execution pipeline may time out while Kraken's worker thread is still waiting
for QueryOrders.  Once AddOrder has returned a genuine txid, persist that exact
exchange id into v363's deferred proof registry immediately.  v363 then performs
read-only exact-id reconciliation and only v328/v346 may promote a confirmed
fill to execution proof.

This patch never treats an ACK as a fill, never retries an order, and never
changes activation, writer, nonce, risk, capital, kill-switch, position, or
protective-exit gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_addorder_txid_capture_v369")
MARKER = "20260918-kraken-addorder-txid-capture-v369"
READY_FLAG = "NIJA_RUNTIME_KRAKEN_ADDORDER_TXID_CAPTURE_V369_READY"
_PATCH_ATTR = "_nija_kraken_addorder_txid_capture_v369"
_LOCK = threading.RLock()


def _extract_txids(response: Any) -> list[str]:
    if not isinstance(response, Mapping):
        return []
    errors = response.get("error")
    if errors:
        return []
    result = response.get("result")
    if not isinstance(result, Mapping):
        return []
    raw = result.get("txid")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for value in raw:
        txid = str(value or "").strip()
        if txid and txid not in out:
            out.append(txid)
    return out


def _record(txid: str, params: Any) -> bool:
    try:
        v363 = importlib.import_module(
            "bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch"
        )
        record = getattr(v363, "record_pending_order", None)
        if not callable(record):
            return False
        payload = dict(params or {}) if isinstance(params, Mapping) else {}
        symbol = str(payload.get("pair") or payload.get("symbol") or "").strip().upper()
        side = str(payload.get("type") or payload.get("side") or "").strip().lower()
        if side not in {"buy", "sell"}:
            side = ""
        return bool(record(order_id=txid, symbol=symbol, side=side, status="acknowledged"))
    except Exception as exc:
        LOGGER.warning(
            "KRAKEN_ADDORDER_TXID_V369_RECORD_FAILED marker=%s txid=%s error=%s:%s "
            "fill_not_assumed=true retry_not_requested=true trading_fail_closed=true",
            MARKER, txid, type(exc).__name__, exc,
        )
        return False


def _patch_class(cls: Any) -> bool:
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def private_call_v369(self: Any, endpoint: str, params: Any = None, *args: Any, **kwargs: Any):
        response = current(self, endpoint, params, *args, **kwargs)
        if str(endpoint or "").strip().lower() != "addorder":
            return response
        txids = _extract_txids(response)
        for txid in txids:
            recorded = _record(txid, params)
            LOGGER.critical(
                "KRAKEN_ADDORDER_TXID_V369_CAPTURED marker=%s txid=%s recorded=%s "
                "exact_exchange_id=true ack_not_fill=true order_retry=false "
                "execution_proof_fabricated=false activation_forced=false safety_gates_bypassed=false",
                MARKER, txid, str(recorded).lower(),
            )
        return response

    setattr(private_call_v369, _PATCH_ATTR, True)
    setattr(private_call_v369, "__wrapped__", current)
    cls._kraken_private_call = private_call_v369
    return True


def _patch_loaded_classes() -> bool:
    ready = False
    seen: set[int] = set()
    for module_name in ("bot.broker_manager", "broker_manager"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        cls = getattr(module, "KrakenBroker", None)
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        ready = bool(_patch_class(cls) or ready)
    return ready


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_addorder_txid_capture_v369"] = READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        patched = _patch_loaded_classes()
        manifest = _register_manifest()
        ready = bool(patched and manifest)
        os.environ[READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_ADDORDER_TXID_CAPTURE_V369_%s marker=%s ready=%s "
            "addorder_txid_capture=true deferred_exact_id_reconciliation=true "
            "ack_not_fill=true order_retry=false order_mutation=false "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "READY_FLAG", "install", "install_import_hook", "_extract_txids", "_patch_class"]
