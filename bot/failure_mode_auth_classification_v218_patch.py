"""Harden failure-mode authentication classification (v218).

The legacy ``handle_api_failure`` classifier treated any exception containing the
substring ``auth`` as INVALID_CREDENTIALS.  Runtime authority errors therefore
matched (``authority`` contains ``auth``) and could be escalated to the
FailureModeManager's EMERGENCY_STOP path even though no credential failure had
occurred.

v218 requires explicit credential/authentication evidence before classifying a
failure as INVALID_CREDENTIALS.  Ordinary authority/readiness/lifecycle failures
remain in their normal retry/monitor taxonomy.  This patch does not suppress a
real 401/unauthorized/invalid-key/signature failure and does not clear an active
kill switch.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.failure_mode_auth_classification_v218")
MARKER = "20260824-failure-mode-auth-classification-v218"
_FLAG = "NIJA_FAILURE_MODE_AUTH_CLASSIFICATION_V218_READY"
_PATCH_ATTR = "_nija_failure_mode_auth_classification_v218"
_LOCK = threading.RLock()
_INSTALLED = False

_AUTH_MARKERS = (
    "invalid credential",
    "invalid credentials",
    "invalid api key",
    "invalid api secret",
    "api key invalid",
    "api key is invalid",
    "authentication failed",
    "authentication failure",
    "authentication error",
    "authentication rejected",
    "unauthorized",
    "invalid signature",
    "signature invalid",
    "permission denied",
    "invalid nonce signature",
    "api-key-invalid",
    "eapi:invalid key",
    "invalid key",
)


def _is_authentication_failure(error: object) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    if "401" in text:
        return True
    return any(marker in text for marker in _AUTH_MARKERS)


def _classify(error: object, failure_type: Any) -> Any:
    text = str(error or "").lower()
    module = importlib.import_module("bot.failure_mode_manager")
    FailureType = getattr(module, "FailureType")
    if "rate limit" in text or "429" in text:
        return FailureType.RATE_LIMIT
    if "timeout" in text or "timed out" in text:
        return FailureType.TIMEOUT
    if _is_authentication_failure(text):
        return FailureType.INVALID_CREDENTIALS
    if "network" in text or "connection" in text:
        return FailureType.NETWORK_LOSS
    if "maintenance" in text:
        return FailureType.EXCHANGE_MAINTENANCE
    return failure_type


def _patch() -> bool:
    module = importlib.import_module("bot.failure_mode_manager")
    current = getattr(module, "handle_api_failure", None)
    FailureType = getattr(module, "FailureType", None)
    getter = getattr(module, "get_failure_mode_manager", None)
    if not callable(current) or FailureType is None or not callable(getter):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def handle_api_failure_v218(error: Exception, context: dict[str, Any] | None = None):
        error_str = str(error or "")
        failure_type = _classify(error_str, FailureType.UNKNOWN_ERROR)
        LOGGER.info(
            "FAILURE_MODE_V218_CLASSIFIED marker=%s failure_type=%s explicit_auth=%s "
            "authority_substring_not_auth=true",
            MARKER,
            getattr(failure_type, "value", str(failure_type)),
            str(_is_authentication_failure(error_str)).lower(),
        )
        manager = getter()
        return manager.handle_failure(
            failure_type=failure_type,
            error_message=error_str,
            context=context,
            raise_on_critical=False,
        )

    setattr(handle_api_failure_v218, _PATCH_ATTR, True)
    setattr(handle_api_failure_v218, "__wrapped__", current)
    module.handle_api_failure = handle_api_failure_v218
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            ok = _patch()
        except Exception as exc:
            LOGGER.critical(
                "FAILURE_MODE_AUTH_V218_INSTALL_FAILED marker=%s err=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ok = False
        if not ok:
            os.environ.pop(_FLAG, None)
            return False
        os.environ[_FLAG] = "1"
        first = not _INSTALLED
        _INSTALLED = True

    if first:
        LOGGER.critical(
            "FAILURE_MODE_AUTH_CLASSIFICATION_V218_READY marker=%s ready=true "
            "generic_auth_substring_removed=true explicit_credential_evidence_required=true "
            "real_401_unauthorized_invalid_key_preserved=true active_stop_unchanged=true "
            "execution_authority_unchanged=true safety_gates_bypassed=false",
            MARKER,
        )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_is_authentication_failure",
    "_classify",
]
