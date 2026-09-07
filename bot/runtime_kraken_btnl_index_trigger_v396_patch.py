"""Kraken BTNL conditional-order trigger repair v396.

BTNL conditional orders can reject the REST AddOrder default trigger reference
(`last`) with: "This market doesn't support Last Trade price. Choose Index."

Patch only v380's private-call boundary so existing native protective SL/TP
orders on authenticated ``:BTNL`` margin exposure send ``trigger=index``.
All existing v380/v392 behavior remains intact, including client-ID collision
recovery, SELL/reduce_only, leverage, authenticated OpenPositions/OpenOrders,
post-submit proof, writer/nonce/rate fencing, and fail-closed behavior.

Ordinary non-BTNL orders and non-conditional private calls are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_btnl_index_trigger_v396")
MARKER = "20260907-kraken-btnl-index-trigger-v396"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_BTNL_INDEX_TRIGGER_V396_READY"
_PATCH_ATTR = "_nija_v396_btnl_index_trigger"
_CONDITIONAL = {
    "stop-loss", "take-profit", "stop-loss-limit", "take-profit-limit",
    "trailing-stop", "trailing-stop-limit",
}


def _is_btnl(value: Any) -> bool:
    return str(value or "").strip().upper().endswith(":BTNL")


def _patch_v380_call() -> bool:
    v380 = importlib.import_module("bot.runtime_kraken_native_margin_backup_v380_patch")
    current = getattr(v380, "_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def call_v396(broker: Any, method: str, params: dict[str, Any], category_name: str):
        safe_params = dict(params or {})
        ordertype = str(safe_params.get("ordertype") or "").strip().lower()
        if (
            str(method or "").strip().lower() == "addorder"
            and _is_btnl(safe_params.get("pair"))
            and ordertype in _CONDITIONAL
        ):
            safe_params["trigger"] = "index"
            LOGGER.info(
                "KRAKEN_BTNL_INDEX_TRIGGER_V396_APPLIED marker=%s pair=%s ordertype=%s "
                "trigger=index reduce_only=%s leverage=%s client_id=%s "
                "ordinary_orders_unchanged=true safety_gates_bypassed=false",
                MARKER,
                safe_params.get("pair"),
                ordertype,
                str(bool(safe_params.get("reduce_only"))).lower(),
                safe_params.get("leverage"),
                safe_params.get("cl_ord_id"),
            )
        return current(broker, method, safe_params, category_name)

    setattr(call_v396, _PATCH_ATTR, True)
    setattr(call_v396, "__wrapped__", current)
    v380._call = call_v396
    return True


def install_import_hook() -> bool:
    ready = _patch_v380_call()
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_KRAKEN_BTNL_INDEX_TRIGGER_V396_%s marker=%s ready=%s "
        "btnl_conditional_trigger=index ordinary_orders_unchanged=true "
        "reduce_only_unchanged=true leverage_unchanged=true client_id_recovery_unchanged=true "
        "openpositions_openorders_proof_unchanged=true new_exposure=false safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_is_btnl", "_patch_v380_call"]
