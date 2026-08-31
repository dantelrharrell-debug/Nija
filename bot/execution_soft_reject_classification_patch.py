from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_soft_reject_classification")
_MARKER = "20260709af"
_V254_MARKER = "20260828-soft-reject-telemetry-v254"
_PATCHED_ATTR = "_nija_execution_soft_reject_classification_20260709af"
_TELEMETRY_PATCHED_ATTR = "_nija_soft_reject_telemetry_v254"

_SOFT_REJECT_MARKERS = (
    "execution gate pending",
    "state_machine=emergency_stop",
    "state_machine=live_pending_confirmation",
    "state_machine=off",
    "terminal_reject_status:unfilled",
    "confirmed_order_rejected:ack_timeout",
    "ack_timeout_no_confirmed_fill",
    "dispatch_disabled",
    "runtime authority convergence lost",
    "executionauthority reject",
    "execution_authority_blocked",
    "execution_authority_runtime",
    # Execution-layer hardening runs before broker submission. These are local
    # safety denials, not proof that an exchange rejected an ECEL-valid order.
    # The denial itself remains fail-closed; this classification only prevents
    # it from being promoted into a synthetic exchange/ECEL fault.
    "hardening_enforcement",
    "execution layer hardening",
    "position_cap_exceeded",
    "position cap reached",
)


def _is_soft_operational_reject(error: Any) -> bool:
    text = str(error or "").strip().lower()
    return any(marker in text for marker in _SOFT_REJECT_MARKERS)


def _patch_telemetry_boundary(cls: type) -> bool:
    """Keep known local/unconfirmed soft outcomes out of exchange rejection telemetry.

    This is deliberately an early defense-in-depth boundary. Soft outcomes are
    still returned as failures to callers; they are simply not promoted into the
    ExchangeKillSwitchProtector order-rejection window unless a concrete exchange
    rejection is independently observed elsewhere.
    """
    current = getattr(cls, "_emit_execution_rejection_telemetry", None)
    if not callable(current):
        return False
    if getattr(current, _TELEMETRY_PATCHED_ATTR, False):
        return True

    @wraps(current)
    def _emit_execution_rejection_telemetry_v254(
        self: Any,
        *,
        symbol: str,
        side: str,
        reason: str,
    ) -> Any:
        if _is_soft_operational_reject(reason):
            logger.warning(
                "EXECUTION_SOFT_REJECT_TELEMETRY_IGNORED marker=%s legacy_marker=%s "
                "symbol=%s side=%s reason=%s exchange_sample_mutated=false "
                "kill_switch_unchanged=true execution_proof_fabricated=false",
                _V254_MARKER,
                _MARKER,
                str(symbol)[:64],
                str(side)[:32],
                str(reason)[:512],
            )
            return None
        return current(self, symbol=symbol, side=side, reason=reason)

    setattr(_emit_execution_rejection_telemetry_v254, _TELEMETRY_PATCHED_ATTR, True)
    setattr(_emit_execution_rejection_telemetry_v254, "__wrapped__", current)
    setattr(cls, "_emit_execution_rejection_telemetry", _emit_execution_rejection_telemetry_v254)
    return True


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False

    telemetry_ok = _patch_telemetry_boundary(cls)
    original = getattr(cls, "_on_order_rejected", None)
    if not callable(original):
        return False
    if getattr(original, _PATCHED_ATTR, False):
        return telemetry_ok

    @wraps(original)
    def _on_order_rejected_soft(self: Any, request: Any, error: str, *args: Any, **kwargs: Any):
        if _is_soft_operational_reject(error):
            logger.warning(
                "EXECUTION_SOFT_REJECT_CLASSIFIED marker=%s v254_marker=%s symbol=%s "
                "side=%s error=%s action=no_ecel_systemerror_no_exchange_sample",
                _MARKER,
                _V254_MARKER,
                getattr(request, "symbol", "unknown"),
                getattr(request, "side", "unknown"),
                error,
            )
            print(
                f"[NIJA-PRINT] EXECUTION_SOFT_REJECT_CLASSIFIED marker={_MARKER} "
                f"v254_marker={_V254_MARKER} symbol={getattr(request, 'symbol', 'unknown')} "
                "action=no_ecel_systemerror_no_exchange_sample",
                flush=True,
            )
            return None
        return original(self, request, error, *args, **kwargs)

    setattr(_on_order_rejected_soft, _PATCHED_ATTR, True)
    setattr(_on_order_rejected_soft, "__wrapped__", original)
    setattr(cls, "_on_order_rejected", _on_order_rejected_soft)
    logger.warning(
        "EXECUTION_SOFT_REJECT_CLASSIFICATION_PATCHED marker=%s v254_marker=%s module=%s "
        "telemetry_guard=%s",
        _MARKER,
        _V254_MARKER,
        getattr(module, "__name__", "unknown"),
        str(telemetry_ok).lower(),
    )
    print(
        f"[NIJA-PRINT] EXECUTION_SOFT_REJECT_CLASSIFICATION_PATCHED marker={_MARKER} "
        f"v254_marker={_V254_MARKER} telemetry_guard={str(telemetry_ok).lower()}",
        flush=True,
    )
    return telemetry_ok


def _patch_loaded() -> None:
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning(
                    "EXECUTION_SOFT_REJECT_CLASSIFICATION_FAILED marker=%s v254_marker=%s module=%s err=%s",
                    _MARKER,
                    _V254_MARKER,
                    name,
                    exc,
                )


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_EXECUTION_SOFT_REJECT_CLASSIFICATION_HOOK_20260709AF", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("execution_pipeline") or "execution_pipeline" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_EXECUTION_SOFT_REJECT_CLASSIFICATION_HOOK_20260709AF", True)
    logger.warning(
        "EXECUTION_SOFT_REJECT_CLASSIFICATION_IMPORT_HOOK marker=%s v254_marker=%s installed=true",
        _MARKER,
        _V254_MARKER,
    )


def install() -> None:
    install_import_hook()
