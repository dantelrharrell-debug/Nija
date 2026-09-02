"""Execution/position readiness convergence v346.

Production on 2026-09-02 after v345 showed live broker execution and a clear kill
switch while activation remained pending on exactly two proofs:
``execution_ready`` and ``position_sync_ready``.  Two liveness gaps caused that
state:

* v320's proactive platform refresh only re-added snapshots while
  ``snapshot_ok`` was still true.  Once platform Kraken crossed the unchanged
  snapshot TTL, ``snapshot_ok`` became false and the stale broker could fall out
  of the proactive candidate set even though readiness correctly remained false.
* v328's canonical confirmed-fill verifier can prove a real final broker fill
  (real order id + final status + fill-specific price/notional), but activation
  provenance accepted only the dedicated heartbeat-trade marker.  A genuine
  live fill therefore could coexist with ``execution_ready=false``.

v346 closes both gaps without fabricating readiness:

1. Any connected PLATFORM broker with a stale/missing authoritative snapshot is
   re-queued through the existing v285/v108 reconciliation worker.  Snapshot TTL
   is unchanged and position readiness is still published only by v285 strong
   proof after a successful authoritative refresh.
2. A fill already accepted by v328's canonical fill verifier writes a fresh
   execution marker with ``source=canonical_confirmed_fill`` and
   ``proof_kind=execution_probe``.  The marker is written only *after* v328 has
   accepted real order-id, final-status and fill-specific price/notional proof.
   v169/v272 are extended to accept that source alongside ``heartbeat_trade``.

No ACK, requested size, quote/current price, stale position snapshot, writer
renewal, nonce, or broker connectivity is promoted to execution/fill/readiness
proof.  Kill switch, writer, nonce, risk, capital, ECEL, minimum-order, position
sync, order ACK, confirmed-fill and activation gates remain fail closed.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_execution_position_readiness_v346")
MARKER = "20260902-runtime-execution-position-readiness-v346"
RELEASE_ID = "20260902-runtime-convergence-v346"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_POSITION_READINESS_V346_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_FILL_PATCH = "_nija_canonical_fill_execution_proof_v346"
_V169_PATCH = "_nija_canonical_fill_source_v346"
_V231_PATCH = "_nija_canonical_fill_source_v346"
_POSITION_PATCH = "_nija_stale_platform_position_refresh_v346"
_ALLOWED_EXECUTION_SOURCES = {"heartbeat_trade", "canonical_confirmed_fill"}


def _write_confirmed_fill_marker(*, result: Mapping[str, Any], symbol: str, side: str, fill_price: float, filled_usd: float) -> bool:
    """Persist execution proof only after v328 has already accepted the fill."""
    try:
        v169 = importlib.import_module("bot.runtime_execution_capital_integrity_v169_patch")
        path_fn = getattr(v169, "_execution_marker_path", None)
        atomic_write = getattr(v169, "_atomic_json_write", None)
        v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
        order_id_fn = getattr(v328, "_order_id", None)
        if not callable(path_fn) or not callable(atomic_write) or not callable(order_id_fn):
            return False
        order_id = str(order_id_fn(result) or "").strip()
        if not order_id or float(fill_price or 0.0) <= 0.0 or float(filled_usd or 0.0) <= 0.0:
            return False
        now = time.time()
        payload = {
            "verified": True,
            "version": 3,
            "stage": "FILL_VERIFY",
            "verified_at_epoch": now,
            "verified_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "source": "canonical_confirmed_fill",
            "proof_kind": "execution_probe",
            "order_id": order_id,
            "symbol": str(symbol or "").strip().upper(),
            "side": str(side or "").strip().lower(),
            "filled_price": float(fill_price),
            "filled_size_usd": float(filled_usd),
            "deployment_id": str(
                os.environ.get("NIJA_DEPLOYMENT_ID")
                or os.environ.get("RENDER_DEPLOY_ID")
                or os.environ.get("RAILWAY_DEPLOYMENT_ID")
                or ""
            ),
            "writer_generation": str(
                os.environ.get("NIJA_WRITER_LEASE_GENERATION")
                or os.environ.get("NIJA_WRITER_GENERATION")
                or ""
            ),
            "nonce_epoch": str(os.environ.get("NIJA_NONCE_EPOCH", "") or ""),
        }
        atomic_write(path_fn(), payload)
        LOGGER.critical(
            "CANONICAL_FILL_EXECUTION_PROOF_V346_RECORDED marker=%s order_id=%s symbol=%s side=%s "
            "fill_price=%.10f filled_usd=%.8f source=canonical_confirmed_fill proof_kind=execution_probe "
            "ack_alone_not_proof=true requested_notional_promoted=false market_price_promoted=false "
            "execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER, order_id, payload["symbol"], payload["side"], float(fill_price), float(filled_usd),
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "CANONICAL_FILL_EXECUTION_PROOF_V346_WRITE_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _patch_v328_confirmed_fill_marker() -> bool:
    module = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
    current = getattr(module, "_normalize_dict_fill", None)
    if not callable(current):
        return False
    if getattr(current, _FILL_PATCH, False):
        return True

    @wraps(current)
    def normalize_v346(result: Mapping[str, Any], *, symbol: str, side: str):
        price, filled_usd = current(result, symbol=symbol, side=side)
        # Reaching here means v328 already proved order-id/final/fill-specific truth.
        _write_confirmed_fill_marker(
            result=result,
            symbol=symbol,
            side=side,
            fill_price=float(price),
            filled_usd=float(filled_usd),
        )
        return price, filled_usd

    setattr(normalize_v346, _FILL_PATCH, True)
    setattr(normalize_v346, "__wrapped__", current)
    module._normalize_dict_fill = normalize_v346
    return True


def _patch_v169_provenance() -> bool:
    module = importlib.import_module("bot.runtime_execution_capital_integrity_v169_patch")
    current = getattr(module, "_execution_provenance_valid", None)
    if not callable(current):
        return False
    if getattr(current, _V169_PATCH, False):
        return True

    @wraps(current)
    def provenance_v346(payload: dict[str, Any], required_stage: str):
        required = str(required_stage or "ORDER_VERIFY").strip().upper()
        source = str(payload.get("source", "") or "").strip().lower()
        kind = str(payload.get("proof_kind", "") or "").strip().lower()
        if required in {"ORDER_VERIFY", "FILL_VERIFY"} and source == "canonical_confirmed_fill":
            if kind != "execution_probe":
                return False, f"execution_proof_source_invalid:source={source}:kind={kind or 'missing'}"
            return True, "canonical_confirmed_fill_provenance_ok"
        return current(payload, required_stage)

    setattr(provenance_v346, _V169_PATCH, True)
    setattr(provenance_v346, "__wrapped__", current)
    module._execution_provenance_valid = provenance_v346
    return True


def _patch_v231_execution_marker() -> bool:
    module = importlib.import_module("bot.runtime_authority_nonce_truth_convergence_v231_patch")
    current = getattr(module, "_execution_marker_proof", None)
    if not callable(current):
        return False
    if getattr(current, _V231_PATCH, False):
        return True

    @wraps(current)
    def execution_marker_v346() -> tuple[bool, str]:
        try:
            tsm = module._tsm()
            status = getattr(tsm, "_heartbeat_verification_status", None)
            if not callable(status):
                return False, "heartbeat_verification_probe_missing"
            ready, detail, meta = status()
            meta = dict(meta or {})
            if not bool(ready):
                return False, str(detail or "execution_marker_not_ready")
            source = str(meta.get("source", "") or "").strip().lower()
            proof_kind = str(meta.get("proof_kind", "") or "").strip().lower()
            required = str(meta.get("required_stage", "ORDER_VERIFY") or "ORDER_VERIFY").strip().upper()
            if required in {"ORDER_VERIFY", "FILL_VERIFY"}:
                if source not in _ALLOWED_EXECUTION_SOURCES or proof_kind != "execution_probe":
                    return False, (
                        "execution_provenance_invalid:"
                        f"source={source or 'missing'}:kind={proof_kind or 'missing'}"
                    )
            stage = str(meta.get("stage", "") or "").strip().upper()
            return True, f"execution_marker_current:stage={stage or 'verified'}:source={source or 'unknown'}"
        except Exception as exc:
            return False, f"execution_marker_probe_failed:{type(exc).__name__}:{exc}"

    setattr(execution_marker_v346, _V231_PATCH, True)
    setattr(execution_marker_v346, "__wrapped__", current)
    module._execution_marker_proof = execution_marker_v346
    return True


def _patch_stale_platform_refresh() -> bool:
    """Include stale/missing connected platform snapshots in v285 refresh candidates."""
    module = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
    current = getattr(module, "_platform_candidates", None)
    snapshot_status = getattr(module, "_snapshot_status", None)
    refresh_interval = getattr(module, "_refresh_interval_s", None)
    connected = getattr(module, "_connected", None)
    label = getattr(module, "_label", None)
    if not callable(current) or not callable(snapshot_status) or not callable(refresh_interval):
        return False
    if getattr(current, _POSITION_PATCH, False):
        return True

    @wraps(current)
    def candidates_v346(manager: Any):
        try:
            found = list(current(manager) or [])
        except Exception:
            found = []
        seen = {id(broker) for _name, broker in found if broker is not None}
        try:
            refresh_after_s = max(1.0, float(refresh_interval()))
        except Exception:
            refresh_after_s = 1.0
        try:
            platform = getattr(manager, "platform_brokers", {}) or {}
            if callable(platform):
                platform = platform()
            items = tuple(dict(platform or {}).items())
        except Exception:
            items = ()

        for broker_type, broker in items:
            if broker is None or id(broker) in seen:
                continue
            try:
                is_connected = bool(connected(broker)) if callable(connected) else bool(getattr(broker, "connected", False))
            except Exception:
                is_connected = False
            if not is_connected:
                continue
            try:
                snapshot_ok, reason, _rows, age_s, _generation = snapshot_status(broker)
                age = float(age_s)
            except Exception as exc:
                snapshot_ok, reason, age = False, f"snapshot_probe_error:{type(exc).__name__}", float("inf")

            # Critical v346 difference: stale/missing snapshots MUST be candidates
            # for authoritative refresh.  This does not make them ready.
            should_refresh = (not bool(snapshot_ok)) or age >= refresh_after_s
            if not should_refresh:
                continue
            try:
                broker_name = str(label(broker_type) if callable(label) else broker_type).strip().lower()
            except Exception:
                broker_name = str(broker_type or "unknown").strip().lower()
            found.append((broker_name or "unknown", broker))
            seen.add(id(broker))
            LOGGER.info(
                "PLATFORM_POSITION_REFRESH_V346_QUEUED marker=%s broker=%s snapshot_ok=%s reason=%s age_s=%s "
                "authoritative_worker_only=true readiness_granted=false ttl_extended=false broker_io_here=false",
                MARKER, broker_name or "unknown", str(bool(snapshot_ok)).lower(), str(reason or "unknown"),
                "inf" if age == float("inf") else f"{age:.3f}",
            )
        return found

    setattr(candidates_v346, _POSITION_PATCH, True)
    setattr(candidates_v346, "__wrapped__", current)
    module._platform_candidates = candidates_v346
    return True


def _wake_position_sync() -> None:
    try:
        v231 = importlib.import_module("bot.runtime_authority_nonce_truth_convergence_v231_patch")
        wake = getattr(v231, "_wake_position_sync_if_needed", None)
        if callable(wake):
            wake()
    except Exception:
        LOGGER.debug("v346 position-sync wake deferred", exc_info=True)


def _wake_activation_after_proof() -> None:
    try:
        v238 = importlib.import_module("bot.runtime_heartbeat_marker_convergence_v238_patch")
        wake = getattr(v238, "_wake_activation_after_genuine_marker", None)
        if callable(wake):
            wake("canonical_confirmed_fill_v346")
    except Exception:
        LOGGER.debug("v346 activation wake deferred", exc_info=True)


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_execution_position_readiness_v346"] = _READY_FLAG
        return True
    except Exception:
        return False


def _worker() -> None:
    while True:
        try:
            _patch_v328_confirmed_fill_marker()
            _patch_v169_provenance()
            _patch_v231_execution_marker()
            _patch_stale_platform_refresh()
            _wake_position_sync()
            _wake_activation_after_proof()
        except Exception:
            LOGGER.debug("V346 worker pulse failed", exc_info=True)
        time.sleep(3.0)


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        fill_ready = provenance_ready = nonce_ready = position_ready = manifest_ready = False
        try:
            fill_ready = _patch_v328_confirmed_fill_marker()
            provenance_ready = _patch_v169_provenance()
            nonce_ready = _patch_v231_execution_marker()
            position_ready = _patch_stale_platform_refresh()
            manifest_ready = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_EXECUTION_POSITION_READINESS_V346_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(fill_ready and provenance_ready and nonce_ready and position_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            _wake_position_sync()
            _wake_activation_after_proof()
            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = threading.Thread(target=_worker, name="ExecutionPositionReadinessV346", daemon=True)
                _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXECUTION_POSITION_READINESS_V346_%s marker=%s ready=%s canonical_confirmed_fill_proof=%s "
            "v169_provenance=%s v272_execution_source=%s stale_platform_refresh=%s manifest=%s "
            "ack_alone_not_execution_proof=true confirmed_fill_required=true stale_snapshot_not_ready=true "
            "snapshot_ttl_unchanged=true requested_notional_promoted=false market_price_promoted=false "
            "writer_nonce_capital_risk_killswitch_ecel_minimum_order_position_fill_gates_unchanged=true "
            "forced_activation=false execution_proof_fabricated=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), str(fill_ready).lower(),
            str(provenance_ready).lower(), str(nonce_ready).lower(), str(position_ready).lower(),
            str(manifest_ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_write_confirmed_fill_marker", "_patch_stale_platform_refresh",
]
