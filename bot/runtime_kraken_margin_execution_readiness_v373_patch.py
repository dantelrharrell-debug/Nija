"""Kraken margin execution-readiness liveness v373.

v372 made Kraken margin execution-proof recovery reuse authenticated v366
OpenPositions metadata and require exact QueryOrders fill evidence.  A startup
ordering race remained: v372 stopped recovery whenever v367's marker probe
momentarily looked ready, even when the canonical readiness table still had
``execution_ready=false``.  When the v169/v346 provenance layer then revoked or
expired that transient marker, recovery no longer ran and activation remained
fail closed with ``marker_missing``.

v373 changes only the *retry stopping condition*.  Recovery stops only after the
canonical readiness table says ``execution_ready=true``.  Until then it continues
to ask v372 for authenticated opening-order candidates, exact-query each candidate
through Kraken QueryOrders, and submit only exact final positive-fill evidence to
the existing v328/v346 verifier chain.

The canonical-fast startup path can intentionally defer the larger post-import
convergence chain that normally installs v169.  Therefore each v373 recovery
cycle also re-invokes v169's real installer until that module itself publishes
its genuine ready flag.  v373 never writes that flag and never treats import
success as readiness.

It does not mark readiness, write an execution marker directly, fabricate a fill,
promote OpenPositions/ACK/current price/requested notional, place an order, force
activation, or weaken any writer/nonce/risk/capital/position/kill-switch/ECEL/
broker-health/minimum-order/order-ack/fill gate.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_margin_execution_readiness_v373")
MARKER = "20260905-runtime-kraken-margin-execution-readiness-v373"
RELEASE_ID = "20260905-runtime-convergence-v373"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_EXECUTION_READINESS_V373_READY"
_V169_READY_FLAG = "NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY"
_PATCH_ATTR = "_nija_v373_margin_execution_readiness"
_LOCK = threading.RLock()


def _v367():
    return importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")


def _v372():
    return importlib.import_module("bot.runtime_kraken_margin_execution_proof_liveness_v372_patch")


def _canonical_execution_ready() -> bool:
    """Read only the canonical readiness table; never infer readiness locally."""
    try:
        readiness = importlib.import_module("bot.readiness_table")
        snapshot = getattr(readiness, "snapshot", None)
        if not callable(snapshot):
            return False
        table = dict(snapshot() or {})
        return bool(table.get("execution_ready", False))
    except Exception:
        return False


def _ensure_v169_ready() -> tuple[bool, str]:
    """Run v169's genuine installer until its own ready flag is published.

    This function deliberately does not set the v169 environment flag.  The
    v169 module owns that truth and publishes it only after all execution,
    authority, import-reassertion, capital-preseed and manifest surfaces install.
    """
    if os.environ.get(_V169_READY_FLAG) == "1":
        return True, "already_ready"
    try:
        module = importlib.import_module("bot.runtime_execution_capital_integrity_v169_patch")
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        if not callable(installer):
            return False, "v169_installer_unavailable"
        installed = bool(installer())
        genuinely_ready = bool(installed and os.environ.get(_V169_READY_FLAG) == "1")
        if genuinely_ready:
            LOGGER.critical(
                "KRAKEN_MARGIN_EXECUTION_READINESS_V373_V169_READY marker=%s "
                "v169_installer_returned=true v169_ready_flag=true readiness_fabricated=false "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
            )
            return True, "v169_genuine_install_ready"
        return False, (
            "v169_install_not_ready:"
            f"installer_returned={str(installed).lower()}:"
            f"ready_flag={os.environ.get(_V169_READY_FLAG, 'missing')}"
        )
    except Exception as exc:
        return False, f"v169_install_exception:{type(exc).__name__}:{exc}"


def recover_execution_proof_once() -> int:
    """Retry exact Kraken proof until canonical execution readiness is true."""
    if _canonical_execution_ready():
        return 0

    v367 = _v367()
    v372 = _v372()
    log_due = getattr(v372, "_log_due", lambda _key, interval_s=30.0: True)

    v169_ready, v169_detail = _ensure_v169_ready()
    if not v169_ready:
        if log_due("v373:v169_not_ready"):
            LOGGER.info(
                "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s "
                "reason=v169_provenance_guard_not_ready detail=%s execution_ready=false "
                "v169_ready_flag_not_written_here=true trading_fail_closed=true "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER, v169_detail,
            )
        return 0

    brokers_fn = getattr(v367, "_account_brokers", None)
    brokers = list(brokers_fn() or []) if callable(brokers_fn) else []
    if not brokers:
        if log_due("v373:no_brokers"):
            LOGGER.info(
                "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s "
                "reason=no_kraken_account_brokers execution_ready=false "
                "trading_fail_closed=true execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
            )
        return 0

    candidates_fn = getattr(v372, "_candidate_opening_orders", None)
    query_fn = getattr(v372, "_exact_queryorders_fill", None)
    if not callable(candidates_fn) or not callable(query_fn):
        if log_due("v373:v372_helpers_missing"):
            LOGGER.error(
                "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s "
                "reason=v372_exact_proof_helpers_unavailable execution_ready=false "
                "trading_fail_closed=true",
                MARKER,
            )
        return 0

    try:
        v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
        normalize = getattr(v328, "_normalize_dict_fill", None)
    except Exception:
        normalize = None
    if not callable(normalize):
        if log_due("v373:v328_missing"):
            LOGGER.error(
                "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s "
                "reason=v328_verifier_unavailable execution_ready=false trading_fail_closed=true",
                MARKER,
            )
        return 0

    private_call_fn = getattr(v367, "_private_call", None)
    for account, broker in brokers:
        account_s = str(account or "")
        try:
            candidates, candidate_reason = candidates_fn(account_s, broker)
        except Exception as exc:
            candidates, candidate_reason = [], f"candidate_exception:{type(exc).__name__}"
        if not candidates:
            if log_due(f"v373:no_candidates:{account_s}"):
                LOGGER.info(
                    "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s account=%s "
                    "reason=no_authenticated_opening_order_candidates detail=%s execution_ready=false "
                    "openpositions_not_fill=true trading_fail_closed=true execution_proof_fabricated=false "
                    "safety_gates_bypassed=false",
                    MARKER, account_s or "unknown", candidate_reason,
                )
            continue

        call = private_call_fn(broker) if callable(private_call_fn) else None
        if not callable(call):
            if log_due(f"v373:private_api:{account_s}"):
                LOGGER.info(
                    "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s account=%s "
                    "reason=kraken_private_api_unavailable execution_ready=false trading_fail_closed=true",
                    MARKER, account_s or "unknown",
                )
            continue

        LOGGER.info(
            "KRAKEN_MARGIN_EXECUTION_READINESS_V373_CANDIDATES marker=%s account=%s candidates=%d "
            "execution_ready=false source=v366_authenticated_openpositions_cache "
            "exact_queryorders_required=true openpositions_not_fill=true execution_proof_fabricated=false",
            MARKER, account_s or "unknown", len(candidates),
        )
        for opening in candidates:
            order_id = str(opening.get("order_id") or "")
            try:
                proof, reason = query_fn(call, opening)
            except Exception as exc:
                proof, reason = None, f"exact_queryorders_exception:{type(exc).__name__}"
            if proof is None:
                if log_due(f"v373:query:{account_s}:{order_id}"):
                    LOGGER.info(
                        "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s account=%s order_id=%s "
                        "reason=%s exact_queryorders_match_required=true execution_ready=false "
                        "trading_fail_closed=true execution_proof_fabricated=false safety_gates_bypassed=false",
                        MARKER, account_s or "unknown", order_id or "unknown", reason,
                    )
                continue

            try:
                normalize(proof, symbol=proof["symbol"], side=proof["side"])
            except Exception as exc:
                if log_due(f"v373:v328:{account_s}:{order_id}"):
                    LOGGER.info(
                        "KRAKEN_MARGIN_EXECUTION_READINESS_V373_DEFERRED marker=%s account=%s order_id=%s "
                        "reason=canonical_v328_rejected:%s:%s execution_ready=false "
                        "trading_fail_closed=true execution_proof_fabricated=false safety_gates_bypassed=false",
                        MARKER, account_s or "unknown", order_id or "unknown", type(exc).__name__, exc,
                    )
                continue

            LOGGER.critical(
                "KRAKEN_MARGIN_EXECUTION_READINESS_V373_RECOVERED marker=%s account=%s order_id=%s "
                "symbol=%s side=%s fill_price=%.10f filled_quantity=%.12f "
                "exact_queryorders_match=true canonical_v328_accepted=true canonical_v346_marker_owner=true "
                "execution_ready_not_written_here=true ack_not_fill=true openpositions_not_fill=true "
                "market_price_promoted=false requested_notional_promoted=false execution_proof_fabricated=false "
                "safety_gates_bypassed=false",
                MARKER, account_s or "unknown", order_id, proof["symbol"], proof["side"],
                float(proof["filled_price"]), float(proof["filled_quantity"]),
            )
            try:
                v346 = importlib.import_module("bot.runtime_execution_position_readiness_v346_patch")
                wake = getattr(v346, "_wake_activation_after_proof", None)
                if callable(wake):
                    wake()
                sync = getattr(v346, "_wake_position_sync", None)
                if callable(sync):
                    sync()
            except Exception:
                LOGGER.debug("v373 activation wake deferred", exc_info=True)
            return 1
    return 0


def _patch_v367_recovery() -> bool:
    module = _v367()
    current = getattr(module, "recover_execution_proof_once", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def recovery_v373():
        return recover_execution_proof_once()

    setattr(recovery_v373, _PATCH_ATTR, True)
    setattr(recovery_v373, "__wrapped__", current)
    module.recover_execution_proof_once = recovery_v373
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_execution_readiness_v373"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        try:
            if os.environ.get("NIJA_RUNTIME_KRAKEN_MARGIN_EXECUTION_PROOF_LIVENESS_V372_READY") != "1":
                raise RuntimeError("v372_not_ready")
            recovery = _patch_v367_recovery()
            manifest = _register_manifest()
            ready = bool(recovery and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_KRAKEN_MARGIN_EXECUTION_READINESS_V373_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

        os.environ[_READY_FLAG] = "1" if ready else "0"
        (LOGGER.critical if ready else LOGGER.error)(
            "RUNTIME_KRAKEN_MARGIN_EXECUTION_READINESS_V373_%s marker=%s ready=%s "
            "canonical_execution_ready_is_only_stop_condition=true transient_marker_does_not_stop_recovery=true "
            "v169_genuine_installer_reasserted=true v169_ready_flag_not_written_here=true "
            "exact_queryorders_match_required=true final_status_required=true positive_fill_quantity_required=true "
            "positive_fill_cost_required=true canonical_v328_verifier_required=true canonical_v346_marker_owner=true "
            "readiness_not_written_here=true ack_not_fill=true openpositions_not_fill=true current_price_not_fill=true "
            "requested_notional_not_fill=true forced_trade=false forced_activation=false execution_proof_fabricated=false "
            "writer_nonce_risk_capital_position_killswitch_ecel_broker_health_minimum_order_ack_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        if ready:
            try:
                recover_execution_proof_once()
            except Exception:
                LOGGER.debug("v373 immediate recovery deferred", exc_info=True)
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "recover_execution_proof_once", "_ensure_v169_ready",
]
