"""Kraken U.S. retail leveraged-order Bitnomial routing convergence v353.

Fresh Render evidence on 2026-09-03 proved that Kraken can return
``EOrder:Reduce only:Non-ECP`` for a leveraged BUY even when NIJA submitted
``reduce_only=False``. Kraken's current API guidance says this error means a US
retail leveraged order used the wrong trading pair and requires ``:BTNL``.

v352 already performs the safe retry: the standard-pair order is submitted
first and a Bitnomial retry occurs only after Kraken explicitly rejects it with
the exact Non-ECP error. v353 only broadens v352's eligibility predicate from
"leveraged reduce-only" to "leveraged AddOrder". It does not change the exact
error requirement, pair canonicalization, one-retry limit, or first-rejection
requirement.

No rejection latch or kill switch is cleared. ACK is not fill. Writer, nonce,
risk, capital, position-sync, ECEL, broker-health, minimum-order, quantity,
order-ack and confirmed-fill gates remain unchanged and fail closed.
"""
from __future__ import annotations

import importlib
import logging
import os
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_kraken_btnl_leveraged_v353")
MARKER = "20260903-runtime-kraken-btnl-leveraged-v353"
RELEASE_ID = "20260903-runtime-convergence-v353"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_BTNL_LEVERAGED_V353_READY"


def _leverage_value(v352: Any, payload: Mapping[str, Any]) -> int:
    try:
        scoped = v352._margin_scope()
    except Exception:
        scoped = {}
    try:
        return int(float((scoped or {}).get("leverage") or payload.get("leverage") or 1))
    except Exception:
        return 1


def _leveraged_addorder(v352: Any, method: Any, payload: Mapping[str, Any]) -> bool:
    """True only for Kraken AddOrder calls carrying leverage greater than 1x."""
    if str(method or "").strip().lower() != "addorder":
        return False
    return _leverage_value(v352, payload) > 1


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_btnl_leveraged_v353"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    try:
        v352 = importlib.import_module("bot.runtime_kraken_btnl_reduce_only_v352_patch")
        if not callable(getattr(v352, "_is_target_addorder", None)):
            raise RuntimeError("v352_target_predicate_unavailable")

        def target_addorder_v353(method: Any, payload: Mapping[str, Any]) -> bool:
            return _leveraged_addorder(v352, method, payload)

        # v352's already-installed private-call wrapper resolves this module
        # global dynamically. Replacing only this predicate preserves v352's
        # exact Non-ECP check, canonical :BTNL conversion, and retry-once path.
        v352._is_target_addorder = target_addorder_v353

        # Cover the flat alias only when it is a distinct loaded module object.
        try:
            flat = importlib.import_module("runtime_kraken_btnl_reduce_only_v352_patch")
        except Exception:
            flat = None
        if flat is not None and flat is not v352 and callable(getattr(flat, "_is_target_addorder", None)):
            def flat_target_addorder_v353(method: Any, payload: Mapping[str, Any]) -> bool:
                return _leveraged_addorder(flat, method, payload)
            flat._is_target_addorder = flat_target_addorder_v353

        manifest = _register_manifest()
        ready = bool(
            manifest
            and _leveraged_addorder(v352, "AddOrder", {"leverage": "2", "reduce_only": False})
            and not _leveraged_addorder(v352, "AddOrder", {"leverage": "1", "reduce_only": False})
            and not _leveraged_addorder(v352, "Balance", {"leverage": "2"})
        )
    except Exception as exc:
        LOGGER.exception(
            "RUNTIME_KRAKEN_BTNL_LEVERAGED_V353_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready = False

    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_BTNL_LEVERAGED_V353_%s marker=%s ready=%s "
        "leveraged_addorder_scope=true exact_non_ecp_error_required_by_v352=true "
        "first_exchange_rejection_required=true retry_once_unchanged=true "
        "btnl_pair_canonicalization_unchanged=true ordinary_spot_orders_unchanged=true "
        "kill_switch_unchanged=true rejection_window_unchanged=true other_exchange_rejections_unchanged=true "
        "ack_not_fill=true confirmed_fill_required=true forced_trade=false forced_activation=false "
        "writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_quantity_order_ack_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_leveraged_addorder",
]
