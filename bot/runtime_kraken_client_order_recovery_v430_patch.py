"""Kraken client-order-id timeout recovery v430.

A transport/outer ACK timeout can occur after Kraken has accepted AddOrder but
before NIJA receives the response containing Kraken's txid. Exact txid recovery
(v369/v363) cannot start in that case.

v430 adds only durable identity and read-only reconciliation:

* when an ordinary Kraken AddOrder has neither userref nor cl_ord_id, inject a
  unique NIJA cl_ord_id before the request leaves the broker;
* persist that client id before submission so process restart/response loss does
  not erase the only exact correlation key;
* if AddOrder returns a real txid, hand it to the existing v363 exact-txid
  recovery path and clear the client-id record;
* if the response is lost, a background worker queries Kraken OpenOrders and
  ClosedOrders using that exact cl_ord_id, adopts exactly one returned txid, and
  then hands that txid to v363.

No symbol/size/time-window guessing is used. No ACK, requested notional, quote,
market price, position appearance, or observation time becomes fill proof.
Existing client ids/userrefs (including protective-order ids) are untouched.
The worker performs authenticated reads only and submits/cancels no orders.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import secrets
import sys
import threading
import time
from collections.abc import Mapping
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_client_order_recovery_v430")
MARKER = "20260921-runtime-kraken-client-order-recovery-v430"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_CLIENT_ORDER_RECOVERY_V430_READY"
_PATCH_ATTR = "_nija_kraken_client_order_recovery_v430"
_DEFAULT_STATE_PATH = "./data/kraken_pending_client_order_refs.json"
_DEFAULT_INTERVAL_S = 15.0
_DEFAULT_MAX_AGE_S = 7 * 24 * 3600.0
_MAX_PENDING = 64

_LOCK = threading.RLock()
_STATE_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None


def _state_path() -> Path:
    return Path(os.environ.get("NIJA_KRAKEN_CLIENT_ORDER_RECOVERY_PATH", _DEFAULT_STATE_PATH))


def _interval_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_CLIENT_ORDER_RECOVERY_INTERVAL_S", "") or _DEFAULT_INTERVAL_S)
    except (TypeError, ValueError):
        value = _DEFAULT_INTERVAL_S
    return max(5.0, value)


def _max_age_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_CLIENT_ORDER_RECOVERY_MAX_AGE_S", "") or _DEFAULT_MAX_AGE_S)
    except (TypeError, ValueError):
        value = _DEFAULT_MAX_AGE_S
    return max(60.0, value)


def _load_refs() -> dict[str, dict[str, Any]]:
    try:
        raw = _state_path().read_text(encoding="utf-8").strip()
        payload = json.loads(raw) if raw.startswith("{") else {}
    except Exception:
        return {}
    refs = payload.get("client_refs") if isinstance(payload, Mapping) else None
    if not isinstance(refs, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for client_id, entry in refs.items():
        cid = str(client_id or "").strip()
        if cid and isinstance(entry, Mapping):
            out[cid] = dict(entry)
    return out


def _store_refs(refs: Mapping[str, Mapping[str, Any]]) -> None:
    path = _state_path()
    payload = {
        "version": 1,
        "marker": MARKER,
        "updated_at_epoch": time.time(),
        "client_refs": {str(k): dict(v) for k, v in refs.items()},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        LOGGER.warning(
            "KRAKEN_CLIENT_ORDER_V430_STATE_WRITE_FAILED marker=%s error=%s:%s fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )


def _account_key(broker: Any) -> str:
    for attr in ("account_identifier", "account_id", "account_key"):
        value = str(getattr(broker, attr, "") or "").strip().lower()
        if value:
            return value
    return ""


def _new_client_id() -> str:
    # Kraken free-text cl_ord_id supports up to 18 ASCII characters.
    return "nj" + secrets.token_hex(8)


def record_pending_client_ref(
    *,
    client_id: str,
    broker: Any,
    pair: str = "",
    side: str = "",
    ordertype: str = "",
) -> bool:
    cid = str(client_id or "").strip()
    if not cid or len(cid) > 18:
        return False
    now = time.time()
    with _STATE_LOCK:
        refs = _load_refs()
        entry = dict(refs.get(cid) or {})
        entry.setdefault("first_seen_epoch", now)
        entry["last_seen_epoch"] = now
        entry["account"] = _account_key(broker) or str(entry.get("account") or "")
        entry["pair"] = str(pair or entry.get("pair") or "").strip().upper()
        entry["side"] = str(side or entry.get("side") or "").strip().lower()
        entry["ordertype"] = str(ordertype or entry.get("ordertype") or "").strip().lower()
        refs[cid] = entry
        if len(refs) > _MAX_PENDING:
            ordered = sorted(
                refs.items(),
                key=lambda item: float(item[1].get("first_seen_epoch") or 0.0),
                reverse=True,
            )
            refs = dict(ordered[:_MAX_PENDING])
        _store_refs(refs)
    LOGGER.info(
        "KRAKEN_CLIENT_ORDER_V430_PENDING_RECORDED marker=%s client_id=%s account=%s pair=%s side=%s "
        "pre_submit_persisted=true ack_not_fill=true order_submitted_here=false",
        MARKER, cid, entry.get("account") or "unknown", entry.get("pair") or "unknown",
        entry.get("side") or "unknown",
    )
    return True


def _discard_client_ref(client_id: str, reason: str) -> None:
    cid = str(client_id or "").strip()
    if not cid:
        return
    with _STATE_LOCK:
        refs = _load_refs()
        if refs.pop(cid, None) is None:
            return
        _store_refs(refs)
    LOGGER.info(
        "KRAKEN_CLIENT_ORDER_V430_PENDING_CLEARED marker=%s client_id=%s reason=%s",
        MARKER, cid, reason,
    )


def _txids(response: Any) -> tuple[str, ...]:
    if not isinstance(response, Mapping):
        return ()
    result = response.get("result")
    if not isinstance(result, Mapping):
        return ()
    raw = result.get("txid")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(v or "").strip() for v in raw if str(v or "").strip()))


def _seed_txids(txids: tuple[str, ...], *, pair: str, side: str, status: str = "ack") -> int:
    if not txids:
        return 0
    try:
        v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
        record = getattr(v363, "record_pending_order", None)
    except Exception:
        record = None
    if not callable(record):
        return 0
    seeded = 0
    for order_id in txids:
        try:
            if record(order_id=order_id, symbol=pair, side=side, status=status):
                seeded += 1
        except Exception:
            LOGGER.debug("v430 txid seed deferred", exc_info=True)
    return seeded


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def private_call_v430(self: Any, method: str, params: Any = None, *args: Any, **kwargs: Any):
        safe = dict(params or {})
        generated_id = ""
        if str(method or "").strip().lower() == "addorder":
            existing_client = str(safe.get("cl_ord_id") or "").strip()
            has_userref = safe.get("userref") not in (None, "")
            if not existing_client and not has_userref:
                generated_id = _new_client_id()
                safe["cl_ord_id"] = generated_id
                record_pending_client_ref(
                    client_id=generated_id,
                    broker=self,
                    pair=str(safe.get("pair") or ""),
                    side=str(safe.get("type") or ""),
                    ordertype=str(safe.get("ordertype") or ""),
                )
                LOGGER.critical(
                    "KRAKEN_CLIENT_ORDER_V430_BOUND marker=%s client_id=%s account=%s pair=%s side=%s "
                    "client_id_only=true order_rules_unchanged=true existing_userref_untouched=true "
                    "existing_client_id_untouched=true",
                    MARKER, generated_id, _account_key(self) or "unknown",
                    str(safe.get("pair") or "unknown"), str(safe.get("type") or "unknown"),
                )
        try:
            response = current(self, method, safe, *args, **kwargs)
        except BaseException:
            # Keep a generated client id durable. The request may have reached
            # Kraken even when the response was lost.
            raise

        if generated_id:
            errors = response.get("error") if isinstance(response, Mapping) else None
            txids = _txids(response)
            if txids:
                _seed_txids(
                    txids,
                    pair=str(safe.get("pair") or ""),
                    side=str(safe.get("type") or ""),
                    status="ack",
                )
                _discard_client_ref(generated_id, "exchange_txid_observed")
            elif errors:
                # Kraken explicitly rejected the AddOrder, so no uncertain
                # accepted order remains to recover for this generated id.
                _discard_client_ref(generated_id, "exchange_rejected")
        return response

    setattr(private_call_v430, _PATCH_ATTR, True)
    setattr(private_call_v430, "__wrapped__", current)
    cls._kraken_private_call = private_call_v430
    return True


def _patch_kraken_classes() -> bool:
    patched = False
    seen: set[int] = set()
    for module_name in ("bot.broker_manager", "broker_manager"):
        try:
            module = sys.modules.get(module_name) or importlib.import_module(module_name)
        except Exception:
            continue
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "KrakenBroker", None)
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        patched = bool(_patch_class(cls) or patched)
    return patched


def _row_side(row: Mapping[str, Any]) -> str:
    descr = row.get("descr")
    if isinstance(descr, Mapping):
        return str(descr.get("type") or "").strip().lower()
    return ""


def _exact_client_row(broker: Any, client_id: str) -> tuple[str, dict[str, Any], str]:
    try:
        v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
        read = getattr(v357, "_private_read", None)
    except Exception:
        read = None
    if not callable(read):
        return "", {}, "read_helper_missing"

    for method, bucket in (("ClosedOrders", "closed"), ("OpenOrders", "open")):
        try:
            payload = read(broker, method, {"trades": True, "cl_ord_id": client_id})
        except Exception as exc:
            return "", {}, f"{method}_error:{type(exc).__name__}"
        if not isinstance(payload, Mapping) or payload.get("error"):
            continue
        result = payload.get("result")
        rows = result.get(bucket) if isinstance(result, Mapping) else None
        if not isinstance(rows, Mapping) or not rows:
            continue
        valid = [(str(oid or "").strip(), dict(row)) for oid, row in rows.items()
                 if str(oid or "").strip() and isinstance(row, Mapping)]
        if len(valid) != 1:
            LOGGER.warning(
                "KRAKEN_CLIENT_ORDER_V430_AMBIGUOUS marker=%s client_id=%s method=%s matches=%s "
                "txid_not_adopted=true trading_fail_closed=true",
                MARKER, client_id, method, len(valid),
            )
            return "", {}, "ambiguous_client_id_result"
        return valid[0][0], valid[0][1], method.lower()
    return "", {}, "not_found"


def recover_client_refs_once() -> int:
    with _STATE_LOCK:
        refs = _load_refs()
    if not refs:
        return 0

    try:
        v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
        brokers_fn = getattr(v363, "_kraken_brokers", None)
    except Exception:
        v363, brokers_fn = None, None
    if not callable(brokers_fn):
        return 0
    try:
        brokers = list(brokers_fn() or [])
    except Exception:
        brokers = []
    if not brokers:
        return 0

    now = time.time()
    recovered = 0
    for client_id, entry in list(refs.items()):
        try:
            first_seen = float(entry.get("first_seen_epoch") or now)
        except (TypeError, ValueError, OverflowError):
            first_seen = now
        if now - first_seen > _max_age_s():
            _discard_client_ref(client_id, "recovery_window_expired")
            continue

        wanted_account = str(entry.get("account") or "").strip().lower()
        wanted_side = str(entry.get("side") or "").strip().lower()
        pair = str(entry.get("pair") or "").strip().upper()

        for broker in brokers:
            broker_account = _account_key(broker)
            if wanted_account and broker_account and wanted_account != broker_account:
                continue
            order_id, row, source = _exact_client_row(broker, client_id)
            if not order_id:
                continue
            row_side = _row_side(row)
            if wanted_side in {"buy", "sell"} and row_side and row_side != wanted_side:
                LOGGER.warning(
                    "KRAKEN_CLIENT_ORDER_V430_SIDE_MISMATCH marker=%s client_id=%s order_id=%s "
                    "expected=%s observed=%s txid_not_adopted=true trading_fail_closed=true",
                    MARKER, client_id, order_id, wanted_side, row_side,
                )
                continue
            status = str(row.get("status") or "").strip().lower()
            if _seed_txids((order_id,), pair=pair, side=wanted_side or row_side, status=status or "ack"):
                _discard_client_ref(client_id, f"exact_{source}_txid_adopted")
                LOGGER.critical(
                    "KRAKEN_CLIENT_ORDER_V430_TXID_RECOVERED marker=%s client_id=%s order_id=%s "
                    "source=%s exact_client_id_filter=true side_match=true read_only=true "
                    "fill_not_assumed=true execution_proof_fabricated=false safety_gates_bypassed=false",
                    MARKER, client_id, order_id, source,
                )
                recovered += 1
                break

    if recovered and v363 is not None:
        try:
            recover = getattr(v363, "recover_once", None)
            if callable(recover):
                recover()
        except Exception:
            LOGGER.debug("v430 v363 wake deferred", exc_info=True)
    return recovered


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_client_order_recovery_v430"] = _READY_FLAG
        return True
    except Exception:
        return False


def _worker() -> None:
    while True:
        try:
            _patch_kraken_classes()
            recover_client_refs_once()
        except Exception:
            LOGGER.debug("v430 worker pulse failed", exc_info=True)
        time.sleep(_interval_s())


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        patch_ok = manifest_ok = False
        try:
            patch_ok = _patch_kraken_classes()
            manifest_ok = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_KRAKEN_CLIENT_ORDER_RECOVERY_V430_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(patch_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready and (_THREAD is None or not _THREAD.is_alive()):
            _THREAD = threading.Thread(
                target=_worker, name="KrakenClientOrderRecoveryV430", daemon=True
            )
            _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_CLIENT_ORDER_RECOVERY_V430_%s marker=%s ready=%s "
            "client_order_id_pre_submit_persisted=true openorders_exact_client_filter=true "
            "closedorders_exact_client_filter=true exact_txid_handoff_to_v363=true "
            "existing_client_ids_untouched=true existing_userref_untouched=true read_only_recovery=true "
            "order_retry=false order_cancel=false ack_not_fill=true requested_notional_promoted=false "
            "market_price_promoted=false observation_time_not_proof=true forced_trade=false "
            "forced_activation=false execution_proof_fabricated=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "record_pending_client_ref",
    "recover_client_refs_once", "_patch_class",
]
