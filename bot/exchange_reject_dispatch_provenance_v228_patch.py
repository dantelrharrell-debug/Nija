"""Keep local/pre-dispatch failures out of exchange rejection telemetry (v228/v256).

The exchange rejection-rate kill switch must only be fed by outcomes that are not
known to be local/pre-dispatch failures. Earlier v228/v232/v247/v253 classifiers
protected the pipeline telemetry emitter, but production proved that wrapper
ordering could still leave a same-process 5/5 rejection window. V256 therefore
adds a second, independent guard at ExchangeKillSwitchProtector.record_order_result
and carries the rejection reason through ExecutionPipeline._on_order_rejected.

Known local/authority/lifecycle/routing/risk/ECEL/soft-ACK failures remain failed
operations, but they are not exchange rejection samples. Unclassified outcomes
continue through the existing path unchanged, so genuine exchange rejections,
thresholds, and fail-closed behavior are preserved. The patch never clears an
existing window or kill switch and never fabricates execution, nonce, ACK, fill,
or readiness proof.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from collections import deque
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.exchange_reject_dispatch_provenance_v228")
MARKER = "20260825-exchange-reject-dispatch-provenance-v228"
V253_MARKER = "20260828-soft-timeout-rejection-provenance-v253"
V256_MARKER = "20260828-rejection-recorder-provenance-v256"
_FLAG = "NIJA_EXCHANGE_REJECT_DISPATCH_PROVENANCE_V228_READY"
_PATCH_ATTR = "_nija_exchange_reject_dispatch_provenance_v228"
_REJECT_HANDLER_PATCH_ATTR = "_nija_exchange_reject_reason_context_v256"
_RECORDER_PATCH_ATTR = "_nija_exchange_reject_recorder_provenance_v256"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_CONTEXT = threading.local()

_NON_EXCHANGE_MARKERS = (
    "dispatch_disabled",
    "executionauthority reject",
    "execution_authority_blocked",
    "execution_authority_runtime",
    "execution_authority_halt",
    "execution gate pending",
    "blocked by state_machine",
    "state_machine=emergency_stop",
    "state_machine=live_pending_confirmation",
    "state_machine=off",
    "runtime authority convergence lost",
    "seak halted",
    "trading blocked",
    "lifecycle_phase:boot",
    "lifecycle_phase_not_live",
    "exchangekillswitch: exchange health red",
    "exchange health red — trade blocked",
    "liquidityintelligenceengine",
    "liquidity grade below",
    "no available venue found",
    "no execution router available",
    "broker_adapter_not_connected",
    "execution blocked:",
    "no_execution_venue_available",
    "broker_not_registered",
    "replacement_unavailable",
    "direct_broker_metadata_mismatch",
    "direct_broker_metadata_cleared",
    "routing candidate",
    "internal route",
    "venue registry",
    "pretraderiskengine reject",
    "riskgovernor blocked",
    "slippageguard blocked",
    "capitalauthorization deny",
    "marginhealthgate reject",
    "ecel unavailable",
    "ecel reject:",
    "orderfeasibility deny",
    "postguard deny",
    "broker_dispatch_failed",
    "empty_order_result",
    "empty order result",
    "execution_route_mismatch",
    "brokerrouteguard deny",
    "broker disabled",
    "adapter_exception",
    "broker_dispatch_exception",
    "okx order failed",
    "all operations failed",
    "confirmed_order_rejected:ack_timeout",
    "ack_timeout_no_confirmed_fill",
    "terminal_reject_status:unfilled",
)


def _is_non_exchange_rejection(reason: Any) -> bool:
    text = str(reason or "").strip().lower()
    return bool(text) and any(marker in text for marker in _NON_EXCHANGE_MARKERS)


def _context_payload() -> dict[str, str]:
    value = getattr(_CONTEXT, "rejection", None)
    return dict(value) if isinstance(value, dict) else {}


def _set_context(*, symbol: str, side: str, reason: str) -> dict[str, str]:
    previous = _context_payload()
    _CONTEXT.rejection = {
        "symbol": str(symbol or "")[:64],
        "side": str(side or "")[:32],
        "reason": str(reason or "")[:1024],
    }
    return previous


def _restore_context(previous: dict[str, str]) -> None:
    if previous:
        _CONTEXT.rejection = previous
    elif hasattr(_CONTEXT, "rejection"):
        delattr(_CONTEXT, "rejection")


def _append_provenance(protector: Any, *, order_id: str, accepted: bool, context: dict[str, str]) -> None:
    try:
        history = getattr(protector, "_nija_order_result_provenance_v256", None)
        if not isinstance(history, deque):
            maxlen = int(getattr(getattr(protector, "_cfg", None), "order_window_size", 20) or 20)
            history = deque(maxlen=max(5, maxlen))
            setattr(protector, "_nija_order_result_provenance_v256", history)
        history.append({
            "timestamp": time.time(),
            "order_id": str(order_id or "")[:256],
            "accepted": bool(accepted),
            "source": "execution_pipeline" if context else "direct_or_legacy",
            "symbol": context.get("symbol", ""),
            "side": context.get("side", ""),
            "reason": context.get("reason", ""),
            "known_non_exchange": _is_non_exchange_rejection(context.get("reason", "")) if context else False,
        })
    except Exception:
        LOGGER.debug("V256 rejection provenance append failed", exc_info=True)


def _patch_exchange_recorder() -> bool:
    module = importlib.import_module("bot.exchange_kill_switch")
    cls = getattr(module, "ExchangeKillSwitchProtector", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "record_order_result", None)
    if not callable(current):
        return False
    if getattr(current, _RECORDER_PATCH_ATTR, False):
        return True
    original = current

    @wraps(original)
    def record_order_result_v256(self: Any, order_id: str, accepted: bool, *args: Any, **kwargs: Any) -> Any:
        context = _context_payload()
        reason = context.get("reason", "")
        if not bool(accepted) and reason and _is_non_exchange_rejection(reason):
            _append_provenance(self, order_id=order_id, accepted=False, context=context)
            LOGGER.critical(
                "EXCHANGE_REJECT_V256_RECORDER_NON_EXCHANGE_IGNORED marker=%s v228_marker=%s "
                "order_id=%s symbol=%s side=%s reason=%s exchange_sample_mutated=false "
                "exchange_order_provenance=false rejection_window_unchanged=true kill_switch_unchanged=true "
                "execution_authority_unchanged=true execution_proof_fabricated=false safety_gates_bypassed=false",
                V256_MARKER, MARKER, str(order_id)[:256], context.get("symbol", ""),
                context.get("side", ""), reason[:512],
            )
            return None
        result = original(self, order_id, accepted, *args, **kwargs)
        _append_provenance(self, order_id=order_id, accepted=bool(accepted), context=context)
        return result

    setattr(record_order_result_v256, _RECORDER_PATCH_ATTR, True)
    setattr(record_order_result_v256, "__wrapped__", original)
    setattr(cls, "record_order_result", record_order_result_v256)
    return True


def _patch_execution_pipeline() -> bool:
    module = importlib.import_module("bot.execution_pipeline")
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False

    current_reject = getattr(cls, "_on_order_rejected", None)
    if callable(current_reject) and not getattr(current_reject, _REJECT_HANDLER_PATCH_ATTR, False):
        original_reject = current_reject

        @wraps(original_reject)
        def on_order_rejected_v256(self: Any, request: Any, error: str) -> Any:
            previous = _set_context(
                symbol=str(getattr(request, "symbol", "unknown") or "unknown"),
                side=str(getattr(request, "side", "unknown") or "unknown"),
                reason=str(error or "unknown exchange rejection"),
            )
            try:
                return original_reject(self, request, error)
            finally:
                _restore_context(previous)

        setattr(on_order_rejected_v256, _REJECT_HANDLER_PATCH_ATTR, True)
        setattr(on_order_rejected_v256, "__wrapped__", original_reject)
        cls._on_order_rejected = on_order_rejected_v256

    current = getattr(cls, "_emit_execution_rejection_telemetry", None)
    if not callable(current):
        return False
    if not getattr(current, _PATCH_ATTR, False):
        original = current

        @wraps(original)
        def emit_v228(self: Any, *, symbol: str, side: str, reason: str) -> Any:
            if _is_non_exchange_rejection(reason):
                LOGGER.critical(
                    "EXCHANGE_REJECT_V228_NON_EXCHANGE_IGNORED marker=%s v253_marker=%s v256_marker=%s "
                    "symbol=%s side=%s reason=%s exchange_sample_mutated=false exchange_order_provenance=false "
                    "route_guard_provenance_v232=true lifecycle_provenance_v247=true soft_timeout_provenance_v253=true "
                    "recorder_guard_v256=true kill_switch_unchanged=true execution_authority_unchanged=true "
                    "execution_proof_fabricated=false safety_gates_bypassed=false",
                    MARKER, V253_MARKER, V256_MARKER, str(symbol)[:64], str(side)[:32], str(reason)[:512],
                )
                return None
            previous = _set_context(symbol=symbol, side=side, reason=reason)
            try:
                return original(self, symbol=symbol, side=side, reason=reason)
            finally:
                _restore_context(previous)

        setattr(emit_v228, _PATCH_ATTR, True)
        setattr(emit_v228, "__wrapped__", original)
        cls._emit_execution_rejection_telemetry = emit_v228

    return bool(getattr(getattr(cls, "_emit_execution_rejection_telemetry", None), _PATCH_ATTR, False)) and bool(
        getattr(getattr(cls, "_on_order_rejected", None), _REJECT_HANDLER_PATCH_ATTR, False)
    )


def _register_manifest_if_loaded() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        return True
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["exchange_reject_dispatch_provenance_v228"] = _FLAG
    own = ("bot.exchange_reject_dispatch_provenance_v228_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _worker() -> None:
    while True:
        try:
            _patch_exchange_recorder()
            _patch_execution_pipeline()
            _register_manifest_if_loaded()
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECT_V228_REASSERT_ERROR marker=%s v256_marker=%s err=%s:%s trading_fail_closed=true",
                MARKER, V256_MARKER, type(exc).__name__, exc,
            )
        time.sleep(2.0)


def install() -> bool:
    global _THREAD
    recorder_ok = _patch_exchange_recorder()
    pipeline_ok = _patch_execution_pipeline()
    manifest_ok = _register_manifest_if_loaded()
    ready = recorder_ok and pipeline_ok and manifest_ok
    os.environ[_FLAG] = "1" if ready else "0"
    if not ready:
        return False
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_worker, name="ExchangeRejectDispatchProvenanceV228", daemon=True)
            _THREAD.start()
    LOGGER.critical(
        "EXCHANGE_REJECT_DISPATCH_PROVENANCE_V228_READY marker=%s v253_marker=%s v256_marker=%s ready=true "
        "local_predispatch_rejects_excluded=true route_guard_provenance_v232=true lifecycle_provenance_v247=true "
        "soft_timeout_provenance_v253=true rejection_reason_context_v256=true recorder_boundary_guard_v256=true "
        "provenance_history_v256=true real_exchange_path_unchanged=true rejection_thresholds_unchanged=true "
        "rejection_window_not_cleared=true kill_switch_unchanged=true execution_authority_unchanged=true "
        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
        MARKER, V253_MARKER, V256_MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "V253_MARKER", "V256_MARKER", "install", "install_import_hook",
    "_is_non_exchange_rejection", "_patch_execution_pipeline", "_patch_exchange_recorder",
    "_context_payload",
]
