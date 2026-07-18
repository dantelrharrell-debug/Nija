"""Converge live broker readiness after successful reconnects.

This patch makes current broker evidence authoritative over stale activation
telemetry, prevents repeated auth-patch installation logs, and keeps terminally
quarantined brokers isolated without blocking healthy venues.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_live_broker_state_convergence")
_MARKER = "20260718-live-broker-state-v1"
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_IMPORT: Callable[..., Any] | None = None
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_RECOVERABLE_STATES = {
    "connect_failed",
    "connection_failed",
    "authentication_failed",
    "auth_failed",
    "degraded",
    "disconnected",
    "failed",
    "unknown",
    "not_started",
}


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _float_env(name: str) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "0") or "0"))
    except (TypeError, ValueError):
        return 0.0


def _reconcile_status(status: dict[str, Any]) -> dict[str, Any]:
    venue = str(status.get("venue", "") or "").strip().lower()
    if not venue:
        return status

    key = venue.upper()
    connected = bool(status.get("connected"))
    trading_ready = bool(status.get("trading_ready"))
    activated = bool(status.get("activated"))
    spendable = max(float(status.get("spendable_quote", 0.0) or 0.0), _float_env(f"NIJA_{key}_SPENDABLE_QUOTE"))
    activation = str(status.get("activation_state", "unknown") or "unknown").strip().lower()

    terminal_quarantine = _truthy(f"NIJA_{key}_CREDENTIALS_QUARANTINED") or _truthy(f"NIJA_{key}_RECONNECT_DISABLED")
    if terminal_quarantine:
        status.update(
            ready=False,
            connected=False,
            trading_ready=False,
            activated=False,
            activation_state="quarantined",
            reason="credentials_quarantined",
        )
        os.environ[f"NIJA_{key}_CONNECTED"] = "0"
        os.environ[f"NIJA_{key}_TRADING_READY"] = "0"
        os.environ[f"NIJA_{key}_ACTIVATED"] = "0"
        os.environ[f"NIJA_{key}_ACTIVATION_STATE"] = "quarantined"
        return status

    # A successfully connected broker with an observed tradable balance must not
    # remain blocked by a stale failure from an earlier activation attempt.
    live_success = connected and trading_ready and activated and spendable > 0.0
    if live_success and activation in _RECOVERABLE_STATES:
        previous = activation
        status.update(
            ready=True,
            activation_state="ready",
            reason="ready",
            spendable_quote=round(spendable, 8),
        )
        os.environ[f"NIJA_{key}_CONNECTED"] = "1"
        os.environ[f"NIJA_{key}_TRADING_READY"] = "1"
        os.environ[f"NIJA_{key}_ACTIVATED"] = "1"
        os.environ[f"NIJA_{key}_ACTIVATION_STATE"] = "ready"
        logger.warning(
            "LIVE_BROKER_STALE_ACTIVATION_RECOVERED marker=%s venue=%s previous=%s "
            "connected=true trading_ready=true activated=true spendable=%.8f",
            _MARKER,
            venue,
            previous,
            spendable,
        )
    return status


def _patch_secondary_readiness(module: ModuleType) -> bool:
    current = getattr(module, "_venue_status", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_live_state_convergence_v1", False):
        return True

    original = current

    def converged(name: str, brokers: dict[str, Any] | None = None) -> dict[str, Any]:
        return _reconcile_status(dict(original(name, brokers)))

    converged._nija_live_state_convergence_v1 = True  # type: ignore[attr-defined]
    converged.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(module, "_venue_status", converged)
    try:
        refresh = getattr(module, "refresh_readiness", None)
        if callable(refresh):
            refresh(force_log=True)
    except Exception:
        logger.exception("LIVE_BROKER_READINESS_REFRESH_FAILED marker=%s", _MARKER)
        return False
    logger.warning("LIVE_BROKER_READINESS_CONVERGENCE_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _patch_auth_recovery(module: ModuleType) -> bool:
    current = getattr(module, "_patch_module", None)
    state_getter = getattr(module, "_state", None)
    if not callable(current) or not callable(state_getter):
        return False
    if getattr(current, "_nija_patch_log_dedupe_v1", False):
        return True

    original = current

    def deduped(target: ModuleType) -> bool:
        state = state_getter()
        with state.lock:
            seen = getattr(state, "patched_modules", None)
            if seen is None:
                seen = set()
                setattr(state, "patched_modules", seen)
            identity = (str(getattr(target, "__name__", "")), id(target))
            if identity in seen:
                return True
        result = bool(original(target))
        if result:
            with state.lock:
                seen.add(identity)
        return result

    deduped._nija_patch_log_dedupe_v1 = True  # type: ignore[attr-defined]
    deduped.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(module, "_patch_module", deduped)
    logger.warning("BROKER_AUTH_PATCH_LOG_DEDUPED marker=%s module=%s", _MARKER, module.__name__)
    return True


class _ExpectedNeedleNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            "PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_DIRECT_NEEDLE_MISSING" in message
            or "PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_TPE_NEEDLE_MISSING" in message
        )


def _install_phase3_noise_filter() -> None:
    target = logging.getLogger("nija.phase3_force_override_terminal_guard")
    if any(isinstance(item, _ExpectedNeedleNoiseFilter) for item in target.filters):
        return
    target.addFilter(_ExpectedNeedleNoiseFilter())


def _patch_loaded() -> None:
    for name in ("secondary_venue_strict_readiness_patch",):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_secondary_readiness(module)
    for name in ("broker_auth_recovery_patch",):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_auth_recovery(module)


def install() -> None:
    global _INSTALLED, _ORIGINAL_IMPORT
    with _LOCK:
        _install_phase3_noise_filter()
        _patch_loaded()
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = importlib.import_module

            def wrapped(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT(name, package)
                if name == "secondary_venue_strict_readiness_patch":
                    _patch_secondary_readiness(module)
                elif name == "broker_auth_recovery_patch":
                    _patch_auth_recovery(module)
                elif name in {"bot.phase3_force_override_terminal_guard_patch", "phase3_force_override_terminal_guard_patch"}:
                    _install_phase3_noise_filter()
                return module

            importlib.import_module = wrapped  # type: ignore[assignment]
        _INSTALLED = True
        os.environ["NIJA_LIVE_BROKER_STATE_CONVERGENCE_INSTALLED"] = "1"
        logger.warning("LIVE_BROKER_STATE_CONVERGENCE_INSTALLED marker=%s", _MARKER)


__all__ = ["install", "_reconcile_status", "_patch_secondary_readiness", "_patch_auth_recovery"]
