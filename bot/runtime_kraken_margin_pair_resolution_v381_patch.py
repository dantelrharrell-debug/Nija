"""Kraken margin pair-resolution bridge v381.

Kraken OpenPositions rows carry the exact margin execution identity such as
``ETHUSD:BTNL``. Public/reference-market helpers still need the standard pair
(for example ``ETHUSD``), so v381 strips the venue suffix only for the shared
public resolver.

Before native backup starts, v381 installs v384, v394 and v395. v394 restores
``:BTNL`` specifically for v380 private protective AddOrder calls and keeps
OpenOrders proof venue-exact. v395 preserves authenticated ``:BTNL`` identity
through emergency software exits while allowing only their read-only price
lookup to use the standard pair.

Once all routing/liveness layers are ready, v381 schedules one immediate v380
audit so an exposed authenticated margin position does not wait for the normal
background poll interval before a correctly-routed native protection attempt.
The audit uses v380's existing authenticated OpenPositions/OpenOrders, reduce-
only, leverage, trigger, writer/nonce/risk, and post-submit proof gates.

No global health state is promoted and no execution gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_margin_pair_resolution_v381")
MARKER = "20260906-kraken-margin-pair-resolution-v381"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_PAIR_RESOLUTION_V381_READY"
_PATCH_ATTR = "_nija_kraken_margin_pair_resolution_v381"
_QUOTES = ("USDT", "USDC", "USD", "EUR")
_IMMEDIATE_RECONCILE_LOCK = threading.Lock()
_IMMEDIATE_RECONCILE_STARTED = False


def _lookup_symbol(value: Any) -> str:
    raw = str(value or "").strip()
    if ":" not in raw:
        return raw
    head, suffix = raw.split(":", 1)
    compact = head.upper().replace("/", "").replace("-", "").replace("_", "")
    if suffix and compact.endswith(_QUOTES):
        return head
    return raw


def _patch_pair_resolver() -> bool:
    module = importlib.import_module("bot.kraken_all_account_exit_runtime_patch")
    current = getattr(module, "_resolve_pair", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def resolve_pair_v381(broker: Any, symbol: str):
        lookup = _lookup_symbol(symbol)
        pair = current(broker, lookup)
        if lookup != str(symbol or "").strip():
            LOGGER.info(
                "KRAKEN_MARGIN_PAIR_V381_LOOKUP marker=%s synthetic_symbol=%s lookup_symbol=%s pair=%s "
                "public_reference_lookup_only=true position_identity_unchanged=true safety_gates_bypassed=false",
                MARKER,
                symbol,
                lookup,
                pair,
            )
        return pair

    setattr(resolve_pair_v381, _PATCH_ATTR, True)
    setattr(resolve_pair_v381, "__wrapped__", current)
    module._resolve_pair = resolve_pair_v381
    return True


def _install_liveness_v384() -> bool:
    try:
        module = importlib.import_module("bot.runtime_kraken_health_user_refresh_v384_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.exception(
            "KRAKEN_MARGIN_PAIR_V381_V384_INSTALL_FAILED marker=%s error=%s:%s "
            "native_backup_deferred=true software_four_way_protection_preserved=true "
            "trading_fail_closed=true safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _install_btnl_routing_v394() -> bool:
    try:
        module = importlib.import_module("bot.runtime_kraken_btnl_native_routing_v394_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.exception(
            "KRAKEN_MARGIN_PAIR_V381_V394_INSTALL_FAILED marker=%s error=%s:%s "
            "native_backup_deferred=true wrong_venue_order_not_accepted_as_protection=true "
            "software_four_way_protection_preserved=true safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _install_btnl_exit_identity_v395() -> bool:
    try:
        module = importlib.import_module("bot.runtime_kraken_btnl_exit_identity_v395_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.exception(
            "KRAKEN_MARGIN_PAIR_V381_V395_INSTALL_FAILED marker=%s error=%s:%s "
            "native_backup_deferred=true software_exit_btnl_identity_unproven=true "
            "spot_fallback_not_promoted=true software_four_way_protection_preserved=true "
            "safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _reassert_v380() -> bool:
    try:
        v380 = importlib.import_module("bot.runtime_kraken_native_margin_backup_v380_patch")
        installer = getattr(v380, "install_import_hook", None)
        if not callable(installer):
            installer = getattr(v380, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.exception(
            "KRAKEN_MARGIN_PAIR_V381_V380_REASSERT_FAILED marker=%s error=%s:%s "
            "new_entries_unchanged=true existing_software_protection_preserved=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _schedule_immediate_v380_reconcile() -> bool:
    """Run one v380 audit promptly after exact BTNL routing is installed.

    This does not bypass any v380 condition. The audit itself must obtain fresh
    authenticated OpenPositions/OpenOrders proof and all existing terminal
    submit gates before an order can be sent. If the hard stop is already
    crossed, v380 still defers to the software emergency-exit authority.
    """
    global _IMMEDIATE_RECONCILE_STARTED
    with _IMMEDIATE_RECONCILE_LOCK:
        if _IMMEDIATE_RECONCILE_STARTED:
            return True
        _IMMEDIATE_RECONCILE_STARTED = True

    def _runner() -> None:
        try:
            v380 = importlib.import_module("bot.runtime_kraken_native_margin_backup_v380_patch")
            audit = getattr(v380, "audit_once", None)
            if not callable(audit):
                LOGGER.error(
                    "KRAKEN_MARGIN_PAIR_V381_IMMEDIATE_RECONCILE_UNAVAILABLE marker=%s "
                    "native_backup_polling_preserved=true safety_gates_bypassed=false",
                    MARKER,
                )
                return
            result = audit()
            LOGGER.critical(
                "KRAKEN_MARGIN_PAIR_V381_IMMEDIATE_RECONCILE_COMPLETE marker=%s ready=%s "
                "authenticated_v380_audit=true reduce_only_unchanged=true openorders_post_submit_proof_required=true "
                "new_exposure=false safety_gates_bypassed=false",
                MARKER, str(bool(isinstance(result, dict) and result.get("ready"))).lower(),
            )
        except Exception as exc:
            LOGGER.exception(
                "KRAKEN_MARGIN_PAIR_V381_IMMEDIATE_RECONCILE_FAILED marker=%s error=%s:%s "
                "native_backup_polling_preserved=true trading_fail_closed=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

    threading.Thread(
        target=_runner,
        name="nija-kraken-native-margin-immediate-reconcile-v396",
        daemon=True,
    ).start()
    LOGGER.critical(
        "KRAKEN_MARGIN_PAIR_V381_IMMEDIATE_RECONCILE_SCHEDULED marker=%s "
        "wait_for_poll_interval=false authenticated_v380_audit=true existing_gates_unchanged=true "
        "new_exposure=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    liveness_ready = _install_liveness_v384()
    pair_ready = _patch_pair_resolver() if liveness_ready else False
    btnl_routing_ready = _install_btnl_routing_v394() if pair_ready else False
    btnl_exit_ready = _install_btnl_exit_identity_v395() if btnl_routing_ready else False
    native_worker_ready = _reassert_v380() if btnl_exit_ready else False
    immediate_reconcile_ready = _schedule_immediate_v380_reconcile() if native_worker_ready else False
    ready = bool(
        liveness_ready and pair_ready and btnl_routing_ready
        and btnl_exit_ready and native_worker_ready and immediate_reconcile_ready
    )
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_KRAKEN_MARGIN_PAIR_RESOLUTION_V381_%s marker=%s ready=%s "
        "v384_health_user_refresh=%s synthetic_suffix_public_lookup_only=true position_identity_unchanged=true "
        "v394_btnl_private_order_routing=%s v395_btnl_software_exit_identity=%s "
        "v380_reasserted=%s immediate_v380_reconcile=%s reduce_only_unchanged=true openorders_proof_venue_exact=true "
        "writer_nonce_risk_killswitch_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        str(liveness_ready).lower(),
        str(btnl_routing_ready).lower(),
        str(btnl_exit_ready).lower(),
        str(native_worker_ready).lower(),
        str(immediate_reconcile_ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_lookup_symbol",
    "_patch_pair_resolver", "_install_liveness_v384", "_install_btnl_routing_v394",
    "_install_btnl_exit_identity_v395", "_schedule_immediate_v380_reconcile",
]
