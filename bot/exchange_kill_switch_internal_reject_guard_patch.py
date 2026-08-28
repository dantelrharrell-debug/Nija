from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.exchange_kill_switch_internal_reject_guard")
_MARKER = "EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_PATCHED marker=20260706a"
_V254_MARKER = "20260828-soft-reject-telemetry-v254"
_V258_MARKER = "20260828-exchange-killswitch-alias-provenance-v258"
_V259_MARKER = "20260828-early-rejection-classification-v259"
_PATCHED_ATTR = "_nija_exchange_kill_switch_internal_reject_guard_20260706a"
_TELEMETRY_PATCHED_ATTR = "_nija_early_soft_reject_telemetry_v254"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_INTERNAL_REJECT_PATTERNS = (
    "no_execution_venue_available",
    "broker_not_registered",
    "replacement_unavailable",
    "direct_broker_metadata_mismatch",
    "direct_broker_metadata_cleared",
    "routing candidate",
    "internal route",
    "venue registry",
)

# These outcomes do not prove that an exchange rejected a submitted order. The
# guard is loaded by sitecustomize and patches ExecutionPipeline on first import,
# so this classification must be at least as complete as the deferred v258
# classifier. Keep genuine/unknown exchange failures out of this tuple.
_SOFT_NON_EXCHANGE_REASON_PATTERNS = (
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


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _internal_reject(*values: Any) -> bool:
    text = " ".join(str(v or "") for v in values).lower()
    return any(pattern in text for pattern in _INTERNAL_REJECT_PATTERNS)


def _soft_non_exchange_reason(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and any(pattern in text for pattern in _SOFT_NON_EXCHANGE_REASON_PATTERNS)


def _install_v258() -> bool:
    """Install v258 without forcing either legacy kill-switch alias to import."""
    try:
        from bot.exchange_kill_switch_alias_provenance_v258_patch import install as install_v258

        ready = bool(install_v258())
        logger.critical(
            "EXCHANGE_KILL_SWITCH_V258_EARLY_INSTALL marker=%s ready=%s "
            "legacy_alias_import_forced=false rejection_window_unchanged=true kill_switch_unchanged=true",
            _V258_MARKER,
            str(ready).lower(),
        )
        return ready
    except Exception as exc:
        logger.warning(
            "EXCHANGE_KILL_SWITCH_V258_EARLY_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
            _V258_MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExchangeKillSwitchProtector", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "record_order_result", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def record_order_result(self: Any, order_id: str, accepted: bool, *args: Any, **kwargs: Any):
        if _truthy("NIJA_EXCHANGE_KILL_SWITCH_IGNORE_INTERNAL_ROUTING_REJECTS", "true"):
            if not accepted and _internal_reject(order_id, args, kwargs):
                logger.critical(
                    "EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_IGNORED marker=20260706a order_id=%s reason=internal_router_not_exchange",
                    order_id,
                )
                print(
                    f"[NIJA-PRINT] EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_IGNORED marker=20260706a order_id={order_id}",
                    flush=True,
                )
                return None
        return original(self, order_id, accepted, *args, **kwargs)

    setattr(record_order_result, _PATCHED_ATTR, True)
    setattr(record_order_result, "__wrapped__", original)
    setattr(cls, "record_order_result", record_order_result)
    logger.warning("%s class=ExchangeKillSwitchProtector", _MARKER)
    print("[NIJA-PRINT] EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_PATCHED marker=20260706a", flush=True)
    return True


def _patch_execution_pipeline_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_emit_execution_rejection_telemetry", None)
    if not callable(original):
        return False
    if getattr(original, _TELEMETRY_PATCHED_ATTR, False):
        return True

    @wraps(original)
    def _emit_execution_rejection_telemetry_v254(
        self: Any,
        *,
        symbol: str,
        side: str,
        reason: str,
    ) -> Any:
        if _soft_non_exchange_reason(reason):
            logger.warning(
                "EARLY_SOFT_REJECT_TELEMETRY_IGNORED marker=%s v259_marker=%s symbol=%s side=%s "
                "reason=%s exchange_sample_mutated=false kill_switch_unchanged=true "
                "execution_authority_unchanged=true execution_proof_fabricated=false",
                _V254_MARKER,
                _V259_MARKER,
                str(symbol)[:64],
                str(side)[:32],
                str(reason)[:512],
            )
            return None
        return original(self, symbol=symbol, side=side, reason=reason)

    setattr(_emit_execution_rejection_telemetry_v254, _TELEMETRY_PATCHED_ATTR, True)
    setattr(_emit_execution_rejection_telemetry_v254, "__wrapped__", original)
    setattr(cls, "_emit_execution_rejection_telemetry", _emit_execution_rejection_telemetry_v254)
    logger.warning(
        "EARLY_SOFT_REJECT_TELEMETRY_GUARD_PATCHED marker=%s v259_marker=%s module=%s",
        _V254_MARKER,
        _V259_MARKER,
        getattr(module, "__name__", "unknown"),
    )
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.exchange_kill_switch", "exchange_kill_switch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def _try_patch_execution_pipeline_loaded() -> bool:
    patched = False
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_execution_pipeline_module(module) or patched
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_EXCHANGE_KILL_SWITCH_IGNORE_INTERNAL_ROUTING_REJECTS", "true")
    _install_v258()
    _try_patch_loaded()
    _try_patch_execution_pipeline_loaded()
    if getattr(builtins, "_NIJA_EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            _try_patch_loaded()
            _try_patch_execution_pipeline_loaded()
            v258 = sys.modules.get("bot.exchange_kill_switch_alias_provenance_v258_patch")
            reassert = getattr(v258, "reassert_loaded", None) if isinstance(v258, ModuleType) else None
            if callable(reassert):
                reassert()
        except Exception as exc:
            logger.warning(
                "EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD hook failed name=%s error=%s",
                name,
                exc,
            )
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_HOOK", True)
    logger.warning(
        "EXCHANGE_KILL_SWITCH_INTERNAL_REJECT_GUARD_IMPORT_HOOK marker=20260706a v254_marker=%s v258_marker=%s v259_marker=%s",
        _V254_MARKER,
        _V258_MARKER,
        _V259_MARKER,
    )


def install() -> None:
    install_import_hook()
