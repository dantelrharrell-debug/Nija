"""Final runtime cleanup for NIJA live execution.

This guard is intentionally one-shot and thread-free. It:
* prevents obsolete convergence watchdog threads from starting;
* freezes canonical scan/Phase-3 wrapper chains after startup convergence;
* hard-isolates OKX entries until connection and spendable balance are observed;
* emits deterministic order-attempt, broker-ack, fill, and rejection telemetry.

It never bypasses writer authority, risk controls, broker validation, minimum
notional checks, or exit protections.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.final_runtime_cleanup")
_MARKER = "20260717-final-runtime-cleanup-v1"
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_IMPORT: Callable[..., Any] | None = None
_ORIGINAL_THREAD_START: Callable[..., Any] | None = None

_OBSOLETE_THREAD_NAMES = {
    "ReentrantScanOwnerRepair",
    "ScanReentrantDelegateRepair",
    "ScanOwnerAuthConvergenceWatchdog",
    "RuntimePostImportConvergence",
    "runtime-authority-convergence-repair",
}

_PIPELINE_ATTR = "_nija_final_execution_telemetry_20260717"
_OKX_GUARD_ATTR = "_nija_okx_unobserved_guard_20260717"


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y",
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _okx_ready() -> tuple[bool, str, float]:
    connected = _truthy("NIJA_OKX_CONNECTED")
    trading_ready = _truthy("NIJA_OKX_TRADING_READY")
    activated = _truthy("NIJA_OKX_ACTIVATED")
    observed = _truthy("NIJA_OKX_BALANCE_OBSERVED") or str(
        os.environ.get("NIJA_OKX_FUNDING_STATUS", "") or ""
    ).strip().lower() in {"observed", "ready", "funded"}
    spendable = max(
        0.0,
        _safe_float(os.environ.get("NIJA_OKX_TRADING_SPENDABLE")),
        _safe_float(os.environ.get("NIJA_OKX_SPENDABLE_QUOTE")),
    )
    minimum = max(0.01, _safe_float(os.environ.get("NIJA_OKX_MIN_ENTRY_USD"), 10.0))
    ready = connected and trading_ready and activated and observed and spendable >= minimum
    if not connected:
        reason = "not_connected"
    elif not trading_ready:
        reason = "trading_not_ready"
    elif not activated:
        reason = "not_activated"
    elif not observed:
        reason = "balance_unobserved"
    elif spendable < minimum:
        reason = f"insufficient_spendable:{spendable:.2f}<{minimum:.2f}"
    else:
        reason = "ready"
    os.environ["NIJA_OKX_ENTRY_ISOLATED"] = "0" if ready else "1"
    os.environ["NIJA_OKX_ENTRY_ISOLATION_REASON"] = reason
    return ready, reason, spendable


def _thread_name(thread: threading.Thread) -> str:
    try:
        return str(getattr(thread, "name", "") or "")
    except Exception:
        return ""


def _install_thread_quiescence() -> None:
    global _ORIGINAL_THREAD_START
    if getattr(threading.Thread.start, "_nija_final_runtime_cleanup", False):
        return
    _ORIGINAL_THREAD_START = threading.Thread.start

    def guarded_start(self: threading.Thread, *args: Any, **kwargs: Any) -> Any:
        name = _thread_name(self)
        if name in _OBSOLETE_THREAD_NAMES:
            logger.critical(
                "LEGACY_RUNTIME_WATCHDOG_SUPPRESSED marker=%s thread=%s action=not_started",
                _MARKER,
                name,
            )
            return None
        return _ORIGINAL_THREAD_START(self, *args, **kwargs)  # type: ignore[misc]

    guarded_start._nija_final_runtime_cleanup = True  # type: ignore[attr-defined]
    guarded_start.__wrapped__ = _ORIGINAL_THREAD_START  # type: ignore[attr-defined]
    threading.Thread.start = guarded_start  # type: ignore[assignment]


def _request_broker_name(request: Any, pipeline: Any = None) -> str:
    for owner in (request, pipeline):
        if owner is None:
            continue
        for attr in (
            "preferred_broker", "execution_broker", "broker", "broker_client",
            "broker_name", "venue", "exchange",
        ):
            try:
                value = getattr(owner, attr, None)
            except Exception:
                continue
            if value is None:
                continue
            raw = getattr(value, "value", value)
            text = f"{raw} {type(value).__name__}".lower().replace("_", "").replace("-", "")
            if "okx" in text:
                return "okx"
            if "kraken" in text:
                return "kraken"
            if "coinbase" in text:
                return "coinbase"
    return "unknown"


def _is_entry(request: Any) -> bool:
    if bool(getattr(request, "reduce_only", False)):
        return False
    intent = str(getattr(request, "intent_type", "entry") or "entry").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    return intent not in {"exit", "close", "reduce", "liquidate", "liquidation"} and effect not in {
        "exit", "close", "reduce",
    }


def _result_field(result: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        try:
            value = getattr(result, name, None)
        except Exception:
            value = None
        if value is not None:
            return value
        if isinstance(result, dict) and name in result:
            return result[name]
    return default


def _make_denial(module: ModuleType, request: Any, reason: str, started: float) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if callable(result_cls):
        return result_cls(
            success=False,
            symbol=str(getattr(request, "symbol", "") or ""),
            side=str(getattr(request, "side", "") or ""),
            size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
            error=reason,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )
    raise RuntimeError(reason)


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    current = getattr(cls, "execute", None) if isinstance(cls, type) else None
    if not callable(current) or getattr(current, _PIPELINE_ATTR, False):
        return bool(callable(current) and getattr(current, _PIPELINE_ATTR, False))
    original = current

    def execute(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        broker = _request_broker_name(request, self)
        symbol = str(getattr(request, "symbol", "") or "")
        side = str(getattr(request, "side", "") or "")
        size = _safe_float(getattr(request, "size_usd", 0.0))
        intent = str(getattr(request, "intent_id", "") or getattr(request, "request_id", "") or "unknown")
        logger.critical(
            "ORDER_ATTEMPT marker=%s intent=%s broker=%s symbol=%s side=%s size_usd=%.8f",
            _MARKER, intent, broker, symbol, side, size,
        )

        if broker == "okx" and _is_entry(request):
            ready, reason, spendable = _okx_ready()
            if not ready:
                error = f"okx_entry_isolated:{reason}"
                logger.critical(
                    "ORDER_REJECTED marker=%s intent=%s broker=okx symbol=%s reason=%s spendable=%.8f",
                    _MARKER, intent, symbol, error, spendable,
                )
                return _make_denial(module, request, error, started)

        try:
            result = original(self, request, *args, **kwargs)
        except Exception as exc:
            logger.critical(
                "ORDER_REJECTED marker=%s intent=%s broker=%s symbol=%s reason=exception:%s",
                _MARKER, intent, broker, symbol, type(exc).__name__,
            )
            raise

        success = bool(_result_field(result, "success", "ok", default=False))
        order_id = str(_result_field(result, "order_id", "broker_order_id", "id", default="") or "")
        fill_price = _safe_float(_result_field(result, "fill_price", "average_price", "avg_price", default=0.0))
        filled_qty = _safe_float(_result_field(result, "filled_quantity", "filled_qty", "quantity", default=0.0))
        status = str(_result_field(result, "status", "state", default="") or "").strip().lower()
        error = str(_result_field(result, "error", "reason", "message", default="") or "")

        acknowledged = bool(order_id) or status in {
            "accepted", "acknowledged", "submitted", "open", "pending", "filled", "partially_filled",
        }
        filled = success and (
            fill_price > 0.0 or filled_qty > 0.0 or status in {"filled", "partially_filled", "closed"}
        )
        if acknowledged:
            logger.critical(
                "BROKER_ACK marker=%s intent=%s broker=%s symbol=%s order_id=%s status=%s",
                _MARKER, intent, broker, symbol, order_id or "unknown", status or "acknowledged",
            )
        if filled:
            logger.critical(
                "ORDER_FILLED marker=%s intent=%s broker=%s symbol=%s order_id=%s fill_price=%.12f filled_qty=%.12f",
                _MARKER, intent, broker, symbol, order_id or "unknown", fill_price, filled_qty,
            )
        elif not success:
            logger.critical(
                "ORDER_REJECTED marker=%s intent=%s broker=%s symbol=%s reason=%s status=%s",
                _MARKER, intent, broker, symbol, error or "unspecified", status or "rejected",
            )
        elif not acknowledged:
            logger.warning(
                "ORDER_RESULT_UNACKNOWLEDGED marker=%s intent=%s broker=%s symbol=%s result_type=%s",
                _MARKER, intent, broker, symbol, type(result).__name__,
            )
        return result

    setattr(execute, _PIPELINE_ATTR, True)
    setattr(execute, _OKX_GUARD_ATTR, True)
    setattr(execute, "__wrapped__", original)
    setattr(cls, "execute", execute)
    logger.critical("FINAL_EXECUTION_TELEMETRY_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _freeze_scan_installers() -> None:
    """Mark canonical owners so legacy watchdog patchers exit without rewrapping."""
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        cls = getattr(module, "NijaCoreLoop", None) if isinstance(module, ModuleType) else None
        if not isinstance(cls, type):
            continue
        for method_name in ("run_scan_phase", "_phase3_scan_and_enter"):
            method = getattr(cls, method_name, None)
            if not callable(method):
                continue
            for attr in (
                "_nija_scan_wrapper_release",
                "_nija_scan_wrapper_canonical_h",
                "_nija_scan_wrapper_canonical_v2",
                "_nija_scan_identity_lock_v2",
                "_nija_final_result_contract_e",
                "_nija_account_scan_serialized_e",
                "_nija_zero_streak_cap_e",
                "_nija_final_runtime_frozen_20260717",
            ):
                try:
                    setattr(method, attr, True)
                except Exception:
                    pass


def _patch_loaded() -> None:
    _freeze_scan_installers()
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_execution_pipeline(module)
    _okx_ready()


def install_import_hook() -> None:
    global _INSTALLED, _ORIGINAL_IMPORT
    with _LOCK:
        if _INSTALLED:
            _patch_loaded()
            return
        _install_thread_quiescence()
        os.environ["NIJA_LEGACY_RUNTIME_WATCHDOGS_DISABLED"] = "1"
        os.environ.setdefault("NIJA_MAX_SCAN_WRAPPER_DEPTH", "64")
        _patch_loaded()
        if not getattr(builtins, "_NIJA_FINAL_RUNTIME_CLEANUP_IMPORT_HOOK", False):
            _ORIGINAL_IMPORT = builtins.__import__

            def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                if name.endswith((
                    "nija_core_loop",
                    "execution_pipeline",
                    "scan_owner_okx_auth_convergence_patch",
                    "reentrant_scan_owner_repair",
                    "runtime_post_import_convergence_patch",
                    "runtime_authority_convergence_repair_patch",
                )):
                    try:
                        _patch_loaded()
                    except Exception:
                        logger.exception("FINAL_RUNTIME_CLEANUP_IMPORT_REPAIR_FAILED marker=%s module=%s", _MARKER, name)
                return module

            builtins.__import__ = guarded_import
            setattr(builtins, "_NIJA_FINAL_RUNTIME_CLEANUP_IMPORT_HOOK", True)
        _INSTALLED = True
        logger.critical(
            "FINAL_RUNTIME_CLEANUP_INSTALLED marker=%s watchdogs=disabled okx_fail_closed=true execution_telemetry=true background_thread=false",
            _MARKER,
        )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_okx_ready",
    "_patch_execution_pipeline",
    "_patch_loaded",
]
