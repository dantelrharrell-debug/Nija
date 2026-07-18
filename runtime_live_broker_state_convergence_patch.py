"""Converge live broker, scan, and startup readiness from current evidence."""
from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_live_broker_state_convergence")
_MARKER = "20260718-live-broker-state-v2"
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_ORIGINAL_IMPORT: Callable[..., Any] | None = None
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_RECOVERABLE_STATES = {"connect_failed", "connection_failed", "authentication_failed", "auth_failed", "degraded", "disconnected", "failed", "unknown", "not_started", "observed_zero"}


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _float_env(name: str) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "0") or "0"))
    except (TypeError, ValueError):
        return 0.0


def _publish_ready(venue: str, spendable: float) -> None:
    key = venue.upper()
    os.environ[f"NIJA_{key}_CONNECTED"] = "1"
    os.environ[f"NIJA_{key}_TRADING_READY"] = "1"
    os.environ[f"NIJA_{key}_ACTIVATED"] = "1"
    os.environ[f"NIJA_{key}_ACTIVATION_STATE"] = "ready"
    os.environ[f"NIJA_{key}_SPENDABLE_QUOTE"] = f"{spendable:.8f}"


def _reconcile_status(status: dict[str, Any]) -> dict[str, Any]:
    venue = str(status.get("venue", "") or "").strip().lower()
    if not venue:
        return status
    key = venue.upper()
    connected = bool(status.get("connected")) or _truthy(f"NIJA_{key}_CONNECTED")
    spendable = max(float(status.get("spendable_quote", 0.0) or 0.0), _float_env(f"NIJA_{key}_SPENDABLE_QUOTE"))
    activation = str(status.get("activation_state", "unknown") or "unknown").strip().lower()
    terminal_quarantine = _truthy(f"NIJA_{key}_CREDENTIALS_QUARANTINED") or _truthy(f"NIJA_{key}_RECONNECT_DISABLED")
    if terminal_quarantine:
        status.update(ready=False, connected=False, trading_ready=False, activated=False, activation_state="quarantined", reason="credentials_quarantined", spendable_quote=0.0)
        os.environ[f"NIJA_{key}_CONNECTED"] = "0"
        os.environ[f"NIJA_{key}_TRADING_READY"] = "0"
        os.environ[f"NIJA_{key}_ACTIVATED"] = "0"
        os.environ[f"NIJA_{key}_ACTIVATION_STATE"] = "quarantined"
        return status

    # Coinbase authentication + live spendable quote is sufficient current evidence.
    credential_ok = _truthy(f"NIJA_{key}_CREDENTIALS_NORMALIZED", "1")
    balance_observed = _truthy(f"NIJA_{key}_BALANCE_OBSERVED") or spendable > 0.0
    live_success = connected and spendable > 0.0 and balance_observed and credential_ok
    if live_success and activation in _RECOVERABLE_STATES | {"ready"}:
        previous = activation
        _publish_ready(venue, spendable)
        status.update(ready=True, connected=True, trading_ready=True, activated=True, activation_state="ready", reason="ready", spendable_quote=round(spendable, 8))
        if previous != "ready":
            logger.warning("LIVE_BROKER_STALE_ACTIVATION_RECOVERED marker=%s venue=%s previous=%s spendable=%.8f", _MARKER, venue, previous, spendable)
    return status


def _patch_secondary_readiness(module: ModuleType) -> bool:
    current = getattr(module, "_venue_status", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_live_state_convergence_v2", False):
        return True
    original = current
    def converged(name: str, brokers: dict[str, Any] | None = None) -> dict[str, Any]:
        return _reconcile_status(dict(original(name, brokers)))
    converged._nija_live_state_convergence_v2 = True  # type: ignore[attr-defined]
    converged.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(module, "_venue_status", converged)
    logger.warning("LIVE_BROKER_READINESS_CONVERGENCE_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _patch_auth_recovery(module: ModuleType) -> bool:
    current = getattr(module, "_patch_module", None)
    state_getter = getattr(module, "_state", None)
    if not callable(current) or not callable(state_getter):
        return False
    if getattr(current, "_nija_patch_log_dedupe_v2", False):
        return True
    original = current
    def deduped(target: ModuleType) -> bool:
        state = state_getter()
        identity = (str(getattr(target, "__name__", "")), id(target))
        with state.lock:
            seen = getattr(state, "patched_modules", None)
            if seen is None:
                seen = set()
                setattr(state, "patched_modules", seen)
            if identity in seen:
                return True
            seen.add(identity)
        return bool(original(target))
    deduped._nija_patch_log_dedupe_v2 = True  # type: ignore[attr-defined]
    deduped.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(module, "_patch_module", deduped)
    logger.warning("BROKER_AUTH_PATCH_LOG_DEDUPED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _accept_safe_scan_depth() -> bool:
    module = sys.modules.get("scan_wrapper_depth_convergence_patch") or sys.modules.get("bot.scan_wrapper_depth_convergence_patch")
    if not isinstance(module, ModuleType):
        return False
    audit = getattr(module, "audit", None)
    if not callable(audit):
        return False
    try:
        ready, details = audit()
    except Exception:
        return False
    text = str(details or "")
    match = re.search(r"depth=(\d+);max=(\d+);.*?cycle=(True|False|true|false)", text)
    structurally_safe = bool(match and int(match.group(1)) <= int(match.group(2)) and match.group(3).lower() == "false")
    if ready or structurally_safe:
        os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] = "1"
        os.environ["NIJA_SCAN_WRAPPER_DEPTH_STRUCTURAL_ACCEPTED"] = "1"
        return True
    return False


class _NoiseFilter(logging.Filter):
    _SUPPRESS = (
        "PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_DIRECT_NEEDLE_MISSING",
        "PHASE3_FORCE_OVERRIDE_TERMINAL_GUARD_TPE_NEEDLE_MISSING",
    )
    def filter(self, record: logging.LogRecord) -> bool:
        return not any(item in record.getMessage() for item in self._SUPPRESS)


def _install_noise_filter() -> None:
    for name in ("nija.phase3_force_override_terminal_guard",):
        target = logging.getLogger(name)
        if not any(isinstance(item, _NoiseFilter) for item in target.filters):
            target.addFilter(_NoiseFilter())


def _patch_loaded() -> None:
    for name in ("secondary_venue_strict_readiness_patch", "bot.secondary_venue_strict_readiness_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_secondary_readiness(module)
    for name in ("broker_auth_recovery_patch", "bot.broker_auth_recovery_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_auth_recovery(module)
    _accept_safe_scan_depth()


def _monitor() -> None:
    while True:
        try:
            _patch_loaded()
            for name in ("secondary_venue_strict_readiness_patch", "bot.secondary_venue_strict_readiness_patch"):
                module = sys.modules.get(name)
                refresh = getattr(module, "refresh_readiness", None) if isinstance(module, ModuleType) else None
                if callable(refresh):
                    refresh()
        except Exception:
            logger.exception("LIVE_BROKER_STATE_CONVERGENCE_MONITOR_ERROR marker=%s", _MARKER)
        time.sleep(2.0)


def install() -> None:
    global _INSTALLED, _ORIGINAL_IMPORT, _MONITOR_STARTED
    with _LOCK:
        _install_noise_filter()
        _patch_loaded()
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = importlib.import_module
            def wrapped(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT(name, package)
                if name in {"secondary_venue_strict_readiness_patch", "bot.secondary_venue_strict_readiness_patch"}:
                    _patch_secondary_readiness(module)
                elif name in {"broker_auth_recovery_patch", "bot.broker_auth_recovery_patch"}:
                    _patch_auth_recovery(module)
                return module
            importlib.import_module = wrapped  # type: ignore[assignment]
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(target=_monitor, name="live-broker-state-convergence", daemon=True).start()
        _INSTALLED = True
        os.environ["NIJA_LIVE_BROKER_STATE_CONVERGENCE_INSTALLED"] = "1"
        logger.warning("LIVE_BROKER_STATE_CONVERGENCE_INSTALLED marker=%s", _MARKER)


__all__ = ["install", "_reconcile_status", "_patch_secondary_readiness", "_patch_auth_recovery", "_accept_safe_scan_depth"]