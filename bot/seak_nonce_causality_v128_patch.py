"""Preserve SEAK fail-closed semantics while fixing activation causality.

Production v127 reached RUNNING_SUPERVISED with the canonical core alive and
registered, then remained blocked because SEAK was halted. Two diagnostic and
escalation defects obscured the true state:

1. activation reads ``seak.halt_reason`` while SEAK stores ``_halt_reason``;
2. nonce-lease verification failures caused by an already-active SEAK halt were
   counted as ``nonce_drift``, eventually tripping the execution circuit breaker
   and escalating a recoverable execution block into process shutdown.

v128 is intentionally narrow. It exposes the existing halt reason read-only and
suppresses only the secondary ``nonce_drift`` anomaly when the failure detail
explicitly proves SEAK is already the cause. It never resumes SEAK, fabricates a
nonce lease, grants execution authority, marks readiness, or relaxes any risk,
writer, broker, bootstrap, or position gate.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.seak_nonce_causality_v128")
MARKER = "20260816-seak-nonce-causality-v128"
RELEASE_ID = "20260816-runtime-convergence-v128"
_FLAG = "NIJA_SEAK_NONCE_CAUSALITY_V128_INSTALLED"
_ANOMALY_ATTR = "_nija_seak_nonce_causality_v128"
_LOCK = threading.RLock()
_INSTALLED = False


def _canonical_import(name: str) -> ModuleType:
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        return existing
    bootstrap = getattr(importlib, "_bootstrap", None)
    gcd_import = getattr(bootstrap, "_gcd_import", None) if bootstrap is not None else None
    if not callable(gcd_import):
        raise RuntimeError("canonical_import_primitive_unavailable")
    module = gcd_import(name)
    if not isinstance(module, ModuleType):
        raise RuntimeError(f"canonical_import_invalid_module:{name}")
    return module


def _patch_seak_halt_reason() -> bool:
    module = _canonical_import("bot.single_execution_authority_kernel")
    cls = getattr(module, "SingleExecutionAuthorityKernel", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "halt_reason", None)
    if isinstance(current, property):
        return True

    def _halt_reason(self: Any) -> str:
        return str(getattr(self, "_halt_reason", "") or "")

    cls.halt_reason = property(_halt_reason)  # type: ignore[attr-defined]
    LOGGER.critical(
        "SEAK_V128_HALT_REASON_EXPOSED marker=%s read_only=true auto_resume=false",
        MARKER,
    )
    return True


def _seak_halted() -> tuple[bool, str]:
    try:
        module = _canonical_import("bot.single_execution_authority_kernel")
        getter = getattr(module, "get_seak", None) or getattr(
            module, "get_single_execution_authority_kernel", None
        )
        seak = getter() if callable(getter) else None
        if seak is None:
            return False, ""
        halted = bool(getattr(seak, "is_halted", False))
        reason = str(
            getattr(seak, "halt_reason", "")
            or getattr(seak, "_halt_reason", "")
            or ""
        )
        return halted, reason
    except Exception:
        return False, ""


def _seak_caused_nonce_detail(detail: str) -> bool:
    text = str(detail or "").strip().lower()
    if "seak halt active" not in text and "seak_halted" not in text:
        return False
    halted, _ = _seak_halted()
    return halted


def _patch_nonce_anomaly_classification() -> bool:
    tsm = _canonical_import("bot.trading_state_machine")
    current = getattr(tsm, "_record_execution_anomaly", None)
    if not callable(current):
        return False
    if bool(getattr(current, _ANOMALY_ATTR, False)):
        return True

    @wraps(current)
    def _record_execution_anomaly_v128(kind: str, detail: str = "") -> None:
        normalized = str(kind or "").strip().lower()
        if normalized == "nonce_drift" and _seak_caused_nonce_detail(detail):
            halted, reason = _seak_halted()
            LOGGER.warning(
                "SEAK_V128_NONCE_DRIFT_SUPPRESSED marker=%s kind=%s seak_halted=%s seak_reason=%s "
                "secondary_circuit_breaker=false execution_remains_fail_closed=true",
                MARKER,
                normalized,
                str(halted).lower(),
                reason or "unknown",
            )
            return
        current(kind, detail)

    setattr(_record_execution_anomaly_v128, _ANOMALY_ATTR, True)
    setattr(_record_execution_anomaly_v128, "__wrapped__", current)
    tsm._record_execution_anomaly = _record_execution_anomaly_v128
    return True


def _patch_v61_seak_probe() -> bool:
    """Make v61 diagnostics use the canonical public/read-only halt reason."""
    v61 = _canonical_import("bot.final_production_activation_repair_v61_patch")
    current = getattr(v61, "_seak_status", None)
    if not callable(current):
        return False
    if bool(getattr(current, _ANOMALY_ATTR, False)):
        return True

    @wraps(current)
    def _seak_status_v128() -> tuple[bool, str]:
        halted, reason = _seak_halted()
        if halted:
            return True, reason or "unknown"
        return False, reason

    setattr(_seak_status_v128, _ANOMALY_ATTR, True)
    setattr(_seak_status_v128, "__wrapped__", current)
    v61._seak_status = _seak_status_v128
    return True


def _patch_release_manifest() -> bool:
    manifest = _canonical_import("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["seak_nonce_causality_v128"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        try:
            seak_ok = _patch_seak_halt_reason()
            anomaly_ok = _patch_nonce_anomaly_classification()
            v61_ok = _patch_v61_seak_probe()
            manifest_ok = _patch_release_manifest()
        except Exception as exc:
            LOGGER.critical(
                "SEAK_NONCE_CAUSALITY_V128_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            seak_ok = anomaly_ok = v61_ok = manifest_ok = False

        if not (seak_ok and anomaly_ok and v61_ok and manifest_ok):
            os.environ.pop(_FLAG, None)
            _INSTALLED = False
            return False

        os.environ[_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "SEAK_NONCE_CAUSALITY_V128_INSTALLED marker=%s release=%s halt_reason_read_only=true "
            "seak_auto_resume=false nonce_bypass=false nonce_drift_causal_filter=true "
            "readiness_synthetic=false execution_authority_unchanged=true",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_seak_caused_nonce_detail",
    "_seak_halted",
]
