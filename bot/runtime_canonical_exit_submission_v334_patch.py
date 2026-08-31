"""Canonical protective-exit submission authority v334.

Production on 2026-08-31 proved the universal exit scanner could finally see a
verified profitable position and a live canonical market price, but then its
submission path called ``broker.place_market_order`` directly.  That bypassed
NIJA's explicit exit request contract, causing two independent failures:

* the terminal execution authority saw an ordinary order during lifecycle BOOT
  and blocked it instead of applying the writer-authorized risk-reducing exit
  gate; and
* a base quantity such as 0.095654 ETH could be interpreted by a downstream
  generic validator as $0.10 notional instead of about $236.

v334 makes every universal protective exit use ``pipeline_order_submitter`` with
``size_type=base``, ``intent_type=exit`` and ``position_effect=close``.  That
preserves the exact broker/account, compiles base quantity to USD using a real
public price, and lets the existing exit-specific pipeline guards distinguish a
position reduction from a new entry.

It also repairs the legacy Kraken account scanner, which already used the
pipeline submitter but omitted the explicit exit intent, and hardens v67's
submission result so a response with no confirmed fill and no real order id can
never be stored as ``accepted pending``.  ``skipped``/ambiguous results remain
retryable failures rather than permanently blocking later exit attempts.

No lifecycle, writer, nonce, broker-health, kill-switch, minimum-order, risk,
position, cost-basis, order-ack or fill-confirmation gate is bypassed.  Entries
remain fail-closed.  v67 remains the authority that closes local tracker state
only after a confirmed fill or independently proven position reduction.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_canonical_exit_submission_v334")
MARKER = "20260831-canonical-exit-submission-v334"
RELEASE_ID = "20260831-runtime-convergence-v334"
_READY_FLAG = "NIJA_RUNTIME_CANONICAL_EXIT_SUBMISSION_V334_READY"
_V67_PATCH_ATTR = "_nija_canonical_exit_submission_v334"
_KRAKEN_PATCH_ATTR = "_nija_kraken_explicit_exit_submission_v334"
_INSTALL_FLAG = "_NIJA_RUNTIME_CANONICAL_EXIT_SUBMISSION_V334"
_LOCK = threading.RLock()

_FILLED = {"filled", "closed", "done", "complete", "completed", "executed", "success"}
_PENDING = {"accepted", "submitted", "pending", "open", "new", "working", "partially_filled"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


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
        return _order_id(result)
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return _order_id(data[0])
    return ""


def _status(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    for key in ("status", "state", "order_status", "result_status"):
        value = _norm(payload.get(key))
        if value:
            return value
    result = payload.get("result")
    if isinstance(result, Mapping):
        return _status(result)
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return _status(data[0])
    return ""


def _account_id(universal: ModuleType, broker: Any) -> str:
    label = str(universal._account_label(broker) or "platform").strip().lower()
    if label.startswith("user:"):
        label = label.split(":", 1)[1]
    if label.endswith(":kraken"):
        label = label.rsplit(":", 1)[0]
    return label or "platform"


def _canonical_submit(
    universal: ModuleType,
    broker: Any,
    pos: Mapping[str, Any],
    *,
    strategy_prefix: str,
) -> dict[str, Any]:
    submitter = importlib.import_module("bot.pipeline_order_submitter")
    submit = getattr(submitter, "submit_market_order_via_pipeline", None)
    if not callable(submit):
        return {"status": "error", "error": "canonical_pipeline_submitter_unavailable"}

    symbol = universal.auto_exit._sym(pos.get("symbol"))
    quantity = universal.auto_exit._quantity(dict(pos))
    side = universal.auto_exit._side(pos.get("side"), dict(pos))
    close_side = "sell" if side in {"long", "buy"} else "buy"
    account = _account_id(universal, broker)
    if not symbol or quantity <= 0.0:
        return {"status": "error", "error": "invalid_exit_symbol_or_quantity"}

    result = submit(
        broker=broker,
        symbol=symbol,
        side=close_side,
        quantity=quantity,
        size_type="base",
        strategy=f"{strategy_prefix}:{side}",
        intent_type="exit",
        account_id_override=account,
        position_effect="close",
        metadata_override={
            "closing_position": True,
            "protective_exit": True,
            "exit_origin": "universal_v67",
            "verified_position_quantity": quantity,
        },
    )
    payload = dict(result) if isinstance(result, Mapping) else {
        "status": "error",
        "error": f"non_mapping_pipeline_result:{result!r}",
    }
    state = _status(payload)
    oid = _order_id(payload)

    # A confirmed fill remains a fill.  A genuine pending state must carry a
    # venue/order identifier.  Everything else is a retryable failure and must
    # never poison v67's pending registry.
    if state in _FILLED:
        return payload
    if oid and (state in _PENDING or not state):
        payload.setdefault("status", "pending")
        return payload
    if oid:
        # Even an unfamiliar state with a real order id must be reconciled, not
        # submitted again.
        payload.setdefault("status", "pending")
        return payload

    error = str(payload.get("error") or payload.get("reason") or state or "unacknowledged_exit_submission")
    LOGGER.warning(
        "CANONICAL_EXIT_V334_NO_ACK marker=%s account=%s symbol=%s side=%s status=%s "
        "order_id_missing=true error=%s pending_not_created=true retry_allowed=true "
        "fill_fabricated=false safety_gates_bypassed=false",
        MARKER, account, symbol, close_side, state or "none", error,
    )
    return {
        "status": "error",
        "error": error,
        "canonical_exit_unacknowledged": True,
        "symbol": symbol,
        "side": close_side,
        "account_id": account,
    }


def _patch_v67() -> bool:
    v67 = importlib.import_module("bot.universal_exit_fill_reconciliation_v67_patch")
    universal = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
    current = getattr(v67, "_submit_exit_once", None)
    if not callable(current):
        return False
    if bool(getattr(current, _V67_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_exit_once_v334(universal_module: ModuleType, broker: Any, pos: dict[str, Any], market: float):
        payload = _canonical_submit(
            universal_module,
            broker,
            pos,
            strategy_prefix="UniversalProtectiveExit",
        )
        state = _status(payload)
        oid = _order_id(payload)
        LOGGER.critical(
            "CANONICAL_EXIT_V334_SUBMISSION_RESULT marker=%s venue=%s account=%s symbol=%s "
            "status=%s order_id=%s canonical_pipeline=true size_type=base intent_type=exit "
            "position_effect=close direct_broker_submit=false",
            MARKER,
            universal_module.auto_exit._broker_label(broker),
            universal_module._account_label(broker),
            universal_module.auto_exit._sym(pos.get("symbol")),
            state or "none",
            oid or "none",
        )
        return payload

    setattr(submit_exit_once_v334, _V67_PATCH_ATTR, True)
    setattr(submit_exit_once_v334, "__wrapped__", current)
    v67._submit_exit_once = submit_exit_once_v334

    # v67's scanner is the active universal scanner and resolves this global at
    # call time, so replacing the module function is sufficient without adding
    # another scanner wrapper.
    return True


def _patch_kraken_account_exit() -> bool:
    module = importlib.import_module("bot.kraken_all_account_exit_runtime_patch")
    current = getattr(module, "_submit_exit", None)
    if not callable(current):
        return False
    if bool(getattr(current, _KRAKEN_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_kraken_exit_v334(broker: Any, account: str, pair: str, quantity: float, reason: str):
        try:
            submitter = importlib.import_module("bot.pipeline_order_submitter")
            submit = getattr(submitter, "submit_market_order_via_pipeline", None)
            if not callable(submit):
                raise RuntimeError("canonical_pipeline_submitter_unavailable")
            result = submit(
                broker=broker,
                symbol=pair,
                side="sell",
                quantity=quantity,
                size_type="base",
                strategy=f"KrakenAccountExit:{reason}",
                intent_type="exit",
                account_id_override=str(account or "platform").strip().lower(),
                position_effect="close",
                metadata_override={
                    "closing_position": True,
                    "protective_exit": True,
                    "exit_origin": "kraken_account_exit",
                    "exit_reason": reason,
                },
            )
            payload = dict(result) if isinstance(result, Mapping) else {
                "status": "error", "error": str(result),
            }
            if _status(payload) not in _FILLED and not _order_id(payload):
                return {
                    "status": "error",
                    "error": str(payload.get("error") or _status(payload) or "unacknowledged_exit_submission"),
                }
            return payload
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    setattr(submit_kraken_exit_v334, _KRAKEN_PATCH_ATTR, True)
    setattr(submit_kraken_exit_v334, "__wrapped__", current)
    module._submit_exit = submit_kraken_exit_v334
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_canonical_exit_submission_v334"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_EXIT_MARKET_PRICE_CONVERGENCE_V333_READY") != "1":
                raise RuntimeError("v333_not_ready")
            v67_ready = _patch_v67()
            kraken_ready = _patch_kraken_account_exit()
            manifest_ready = _register_manifest()
            ready = bool(v67_ready and kraken_ready and manifest_ready)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "CANONICAL_EXIT_V334_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_CANONICAL_EXIT_SUBMISSION_V334_%s marker=%s ready=%s "
            "universal_v67_pipeline_submit=true kraken_account_exit_explicit_intent=true "
            "size_type_base=true intent_type_exit=true position_effect_close=true "
            "writer_authorized_exit_gate_preserved=true direct_broker_submit_disabled_for_universal_exit=true "
            "empty_order_id_pending_blocked=true fill_confirmation_preserved=true entries_unchanged=true "
            "lifecycle_writer_nonce_broker_health_killswitch_minimum_order_gates_unchanged=true "
            "forced_loss_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_canonical_submit", "_order_id", "_status",
]
