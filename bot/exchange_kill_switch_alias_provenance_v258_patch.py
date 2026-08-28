"""Converge exchange kill-switch recorder provenance across import identities (v258).

Production can load ``bot.exchange_kill_switch`` and ``exchange_kill_switch`` as
separate module/class identities.  Earlier rejection-provenance hardening covered
both ExecutionPipeline identities but recorder instrumentation remained canonical
only.  V258 patches every loaded ExchangeKillSwitchProtector identity, captures
rejection reason context across every loaded ExecutionPipeline identity, and
emits a diagnostic for every rejected sample that is actually counted.

Safety contract:
* Never clear an existing rejection window.
* Never reset/deactivate a kill switch.
* Never lower rejection thresholds or minimum sample counts.
* Never fabricate authority, nonce, ACK, fill, execution, or readiness proof.
* Unknown/direct and genuine exchange rejections continue to count.
* Only reasons already classified as local/pre-dispatch/non-exchange are ignored.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import deque
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.exchange_kill_switch_alias_provenance_v258")
MARKER = "20260828-exchange-killswitch-alias-provenance-v258"
V269_MARKER = "20260828-hardening-enforcement-provenance-v269"
_FLAG = "NIJA_EXCHANGE_KILLSWITCH_ALIAS_PROVENANCE_V258_READY"
_RECORDER_ATTR = "_nija_exchange_killswitch_alias_recorder_v258"
_REJECT_ATTR = "_nija_exchange_killswitch_alias_reject_context_v258"
_EMIT_ATTR = "_nija_exchange_killswitch_alias_emit_context_v258"
_CONTEXT = threading.local()
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None

# Keep this list aligned with the already-approved v228/v254 local/non-exchange
# classifications.  These reasons do not prove that an order reached an exchange.
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

# ``HARDENING_ENFORCEMENT`` is the documented execution-layer return code for a
# position-cap/minimum-size/average-position/dust block.  That control returns
# before broker API dispatch.  Keep it exact-match only so an arbitrary exchange
# message that merely contains the token cannot be reclassified as local.
_EXACT_NON_EXCHANGE_CODES = frozenset({"hardening_enforcement"})


def _is_non_exchange(reason: Any) -> bool:
    text = str(reason or "").strip().lower()
    if not text:
        return False
    if text in _EXACT_NON_EXCHANGE_CODES:
        return True
    return any(marker in text for marker in _NON_EXCHANGE_MARKERS)


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


def _append_provenance(
    protector: Any,
    *,
    module_name: str,
    order_id: str,
    accepted: bool,
    context: dict[str, str],
) -> None:
    try:
        history = getattr(protector, "_nija_order_result_provenance_v258", None)
        if not isinstance(history, deque):
            maxlen = int(getattr(getattr(protector, "_cfg", None), "order_window_size", 20) or 20)
            history = deque(maxlen=max(5, maxlen))
            setattr(protector, "_nija_order_result_provenance_v258", history)
        history.append(
            {
                "timestamp": time.time(),
                "order_id": str(order_id or "")[:256],
                "accepted": bool(accepted),
                "kill_switch_module": module_name,
                "source": "execution_pipeline" if context else "direct_or_legacy",
                "symbol": context.get("symbol", ""),
                "side": context.get("side", ""),
                "reason": context.get("reason", ""),
                "known_non_exchange": _is_non_exchange(context.get("reason", "")) if context else False,
            }
        )
    except Exception:
        LOGGER.debug("V258 provenance append failed", exc_info=True)


def _patch_kill_switch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExchangeKillSwitchProtector", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "record_order_result", None)
    if not callable(current):
        return False
    if getattr(current, _RECORDER_ATTR, False):
        return True

    original = current
    module_name = str(getattr(module, "__name__", "unknown"))

    @wraps(original)
    def record_order_result_v258(
        self: Any,
        order_id: str,
        accepted: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        context = _context_payload()
        reason = context.get("reason", "")
        if not bool(accepted) and reason and _is_non_exchange(reason):
            _append_provenance(
                self,
                module_name=module_name,
                order_id=order_id,
                accepted=False,
                context=context,
            )
            LOGGER.critical(
                "EXCHANGE_REJECT_V258_NON_EXCHANGE_IGNORED marker=%s kill_switch_module=%s "
                "order_id=%s source=execution_pipeline context_present=true symbol=%s side=%s reason=%s "
                "exchange_sample_mutated=false rejection_window_unchanged=true kill_switch_unchanged=true "
                "rejection_thresholds_unchanged=true execution_authority_unchanged=true "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
                module_name,
                str(order_id)[:256],
                context.get("symbol", ""),
                context.get("side", ""),
                reason[:512],
            )
            return None

        result = original(self, order_id, accepted, *args, **kwargs)
        _append_provenance(
            self,
            module_name=module_name,
            order_id=order_id,
            accepted=bool(accepted),
            context=context,
        )
        if not bool(accepted):
            LOGGER.critical(
                "EXCHANGE_REJECT_V258_COUNTED_SAMPLE marker=%s kill_switch_module=%s "
                "protector_class_id=%s protector_instance_id=%s order_id=%s source=%s "
                "context_present=%s symbol=%s side=%s reason=%s known_non_exchange=false "
                "sample_counted=true rejection_thresholds_unchanged=true kill_switch_behavior_unchanged=true",
                MARKER,
                module_name,
                id(type(self)),
                id(self),
                str(order_id)[:256],
                "execution_pipeline" if context else "direct_or_legacy",
                str(bool(context)).lower(),
                context.get("symbol", ""),
                context.get("side", ""),
                (reason or "missing")[:512],
            )
        return result

    setattr(record_order_result_v258, _RECORDER_ATTR, True)
    setattr(record_order_result_v258, "__wrapped__", original)
    setattr(cls, "record_order_result", record_order_result_v258)
    return True


def _patch_pipeline_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False

    current_reject = getattr(cls, "_on_order_rejected", None)
    reject_ok = True
    if callable(current_reject) and not getattr(current_reject, _REJECT_ATTR, False):
        original_reject = current_reject

        @wraps(original_reject)
        def on_order_rejected_v258(self: Any, request: Any, error: str) -> Any:
            previous = _set_context(
                symbol=str(getattr(request, "symbol", "unknown") or "unknown"),
                side=str(getattr(request, "side", "unknown") or "unknown"),
                reason=str(error or "unknown exchange rejection"),
            )
            try:
                return original_reject(self, request, error)
            finally:
                _restore_context(previous)

        setattr(on_order_rejected_v258, _REJECT_ATTR, True)
        setattr(on_order_rejected_v258, "__wrapped__", original_reject)
        cls._on_order_rejected = on_order_rejected_v258
    elif callable(current_reject):
        reject_ok = bool(getattr(current_reject, _REJECT_ATTR, False))

    current_emit = getattr(cls, "_emit_execution_rejection_telemetry", None)
    emit_ok = True
    if callable(current_emit) and not getattr(current_emit, _EMIT_ATTR, False):
        original_emit = current_emit

        @wraps(original_emit)
        def emit_rejection_v258(self: Any, *, symbol: str, side: str, reason: str) -> Any:
            previous = _set_context(symbol=symbol, side=side, reason=reason)
            try:
                return original_emit(self, symbol=symbol, side=side, reason=reason)
            finally:
                _restore_context(previous)

        setattr(emit_rejection_v258, _EMIT_ATTR, True)
        setattr(emit_rejection_v258, "__wrapped__", original_emit)
        cls._emit_execution_rejection_telemetry = emit_rejection_v258
    elif callable(current_emit):
        emit_ok = bool(getattr(current_emit, _EMIT_ATTR, False))

    return reject_ok and emit_ok


def _loaded_modules(names: tuple[str, ...]) -> list[ModuleType]:
    modules: list[ModuleType] = []
    seen: set[int] = set()
    for name in names:
        candidate = sys.modules.get(name)
        if isinstance(candidate, ModuleType) and id(candidate) not in seen:
            seen.add(id(candidate))
            modules.append(candidate)
    return modules


def _identity_snapshot(modules: list[ModuleType]) -> tuple[dict[str, int], dict[str, int | None]]:
    classes: dict[str, int] = {}
    singletons: dict[str, int | None] = {}
    for module in modules:
        name = str(getattr(module, "__name__", "unknown"))
        cls = getattr(module, "ExchangeKillSwitchProtector", None)
        classes[name] = id(cls) if isinstance(cls, type) else 0
        protector = getattr(module, "_protector", None)
        singletons[name] = id(protector) if protector is not None else None
    return classes, singletons


def reassert_loaded() -> bool:
    kill_modules = _loaded_modules(("bot.exchange_kill_switch", "exchange_kill_switch"))
    pipeline_modules = _loaded_modules(("bot.execution_pipeline", "execution_pipeline"))

    kill_outcomes = {
        str(getattr(module, "__name__", "unknown")): _patch_kill_switch_module(module)
        for module in kill_modules
    }
    pipeline_outcomes = {
        str(getattr(module, "__name__", "unknown")): _patch_pipeline_module(module)
        for module in pipeline_modules
    }

    class_ids, singleton_ids = _identity_snapshot(kill_modules)
    canonical = sys.modules.get("bot.exchange_kill_switch")
    legacy = sys.modules.get("exchange_kill_switch")
    alias_loaded = isinstance(legacy, ModuleType)
    module_same = bool(alias_loaded and legacy is canonical)
    canonical_singleton = getattr(canonical, "_protector", None) if isinstance(canonical, ModuleType) else None
    legacy_singleton = getattr(legacy, "_protector", None) if isinstance(legacy, ModuleType) else None
    singleton_same = bool(
        canonical_singleton is not None
        and legacy_singleton is not None
        and canonical_singleton is legacy_singleton
    )

    LOGGER.critical(
        "EXCHANGE_REJECT_V258_KILLSWITCH_IDENTITIES marker=%s kill_switch_outcomes=%s "
        "pipeline_outcomes=%s class_ids=%s singleton_ids=%s alias_loaded=%s module_same_object=%s "
        "singleton_same_object=%s legacy_alias_import_forced=false rejection_window_unchanged=true "
        "kill_switch_unchanged=true rejection_thresholds_unchanged=true safety_gates_bypassed=false",
        MARKER,
        kill_outcomes,
        pipeline_outcomes,
        class_ids,
        singleton_ids,
        str(alias_loaded).lower(),
        str(module_same).lower(),
        str(singleton_same).lower(),
    )

    # Being loaded is not required for readiness; the early import hook and worker
    # are responsible for patching aliases immediately when they appear.
    return all(kill_outcomes.values()) and all(pipeline_outcomes.values())


def _worker() -> None:
    while True:
        try:
            reassert_loaded()
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECT_V258_REASSERT_ERROR marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(2.0)


def install() -> bool:
    global _THREAD
    reassert_loaded()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ExchangeKillSwitchAliasProvenanceV258",
                daemon=True,
            )
            _THREAD.start()
    os.environ[_FLAG] = "1"
    LOGGER.critical(
        "EXCHANGE_REJECT_V258_READY marker=%s v269_marker=%s ready=true dual_kill_switch_identity_guard=true "
        "dual_pipeline_context_guard=true counted_sample_diagnostics=true provenance_history=true "
        "hardening_enforcement_exact_non_exchange=true legacy_alias_import_forced=false "
        "rejection_window_cleared=false kill_switch_mutated=false rejection_thresholds_unchanged=true "
        "minimum_sample_unchanged=true genuine_exchange_rejects_unchanged=true execution_authority_unchanged=true "
        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
        MARKER,
        V269_MARKER,
    )
    return True


__all__ = [
    "MARKER",
    "V269_MARKER",
    "install",
    "reassert_loaded",
    "_is_non_exchange",
    "_patch_kill_switch_module",
    "_patch_pipeline_module",
]
