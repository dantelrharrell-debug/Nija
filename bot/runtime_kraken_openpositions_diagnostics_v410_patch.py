"""Sanitized Kraken OpenPositions failure diagnostics v410.

v366 intentionally fails closed when an authenticated ``OpenPositions`` read
raises, but it only records the Python exception class.  That is insufficient to
distinguish a permission/authentication problem from nonce authority, circuit
breaker, rate-limit, or transport failures on registered-user accounts.

This patch adds classification-only telemetry around the existing private-call
boundary.  It never changes return values, retries, exception propagation,
position truth, readiness, execution authority, or any writer/nonce/risk/
kill-switch gate.  Exception messages are not emitted; only a bounded category
and exception type are logged so credentials, signatures, nonces, and request
payloads cannot leak through this diagnostic surface.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_openpositions_diagnostics_v410")
MARKER = "20260914-kraken-openpositions-diagnostics-v410"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_OPENPOSITIONS_DIAGNOSTICS_V410_READY"
_PATCH_ATTR = "_nija_kraken_openpositions_diagnostics_v410"


def _classify_exception(exc: BaseException) -> str:
    text = str(exc or "").lower()
    if "circuit breaker" in text:
        return "circuit_breaker_open"
    if "nonce readiness" in text or "nonce issuance" in text or "nonce manager" in text:
        return "nonce_authority_unready"
    if "writer authority" in text or "writer lease" in text or "lease unavailable" in text:
        return "writer_authority_unready"
    if "permission" in text or "eapi:permission" in text:
        return "api_permission_denied"
    if "invalid key" in text or "api key" in text or "authentication" in text or "eapi:invalid key" in text:
        return "api_authentication_rejected"
    if "invalid nonce" in text or "eapi:invalid nonce" in text:
        return "kraken_invalid_nonce"
    if "rate limit" in text or "too many requests" in text or "eapi:rate limit" in text:
        return "kraken_rate_limited"
    if "timeout" in text or "timed out" in text:
        return "transport_timeout"
    if any(token in text for token in ("connection", "network", "ssl", "broken pipe", "eof", "503", "504")):
        return "transport_failure"
    if "service unavailable" in text or "temporarily unavailable" in text:
        return "kraken_service_unavailable"
    return "unclassified_exception"


def _patch_private_call() -> bool:
    module = importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")
    current = getattr(module, "_private_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def private_call_v410(broker: Any):
        call = current(broker)
        if not callable(call):
            return call
        if bool(getattr(call, _PATCH_ATTR, False)):
            return call

        @wraps(call)
        def classified_call(method: Any, params: Any = None):
            try:
                if params is None:
                    return call(method)
                return call(method, params)
            except Exception as exc:
                if str(method or "").strip().lower() == "openpositions":
                    LOGGER.error(
                        "KRAKEN_OPENPOSITIONS_DIAGNOSTIC_V410 marker=%s exception_type=%s "
                        "category=%s message_redacted=true credentials_redacted=true params_redacted=true "
                        "return_value_unchanged=true exception_rethrown=true position_truth_unchanged=true "
                        "readiness_unchanged=true execution_authority_unchanged=true safety_gates_bypassed=false",
                        MARKER,
                        type(exc).__name__,
                        _classify_exception(exc),
                    )
                raise

        setattr(classified_call, _PATCH_ATTR, True)
        setattr(classified_call, "__wrapped__", call)
        return classified_call

    setattr(private_call_v410, _PATCH_ATTR, True)
    setattr(private_call_v410, "__wrapped__", current)
    module._private_call = private_call_v410
    return True


def install_import_hook() -> bool:
    try:
        ready = _patch_private_call()
    except Exception as exc:
        ready = False
        LOGGER.error(
            "KRAKEN_OPENPOSITIONS_DIAGNOSTIC_V410_INSTALL_FAILED marker=%s exception_type=%s "
            "message_redacted=true behavior_unchanged=true trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
        )
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_KRAKEN_OPENPOSITIONS_DIAGNOSTICS_V410_%s marker=%s ready=%s "
        "classification_only=true message_redacted=true return_values_unchanged=true exceptions_rethrown=true "
        "position_truth_unchanged=true readiness_unchanged=true execution_authority_unchanged=true "
        "writer_nonce_risk_killswitch_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_classify_exception", "_patch_private_call"]
