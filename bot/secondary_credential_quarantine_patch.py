"""Quarantine secondary venues after definitive credential rejection.

Fatal OKX credential responses are process-global facts, not per-client state.
Once observed, all private requests and connection attempts are blocked until a
new deployment starts with replacement credentials. Healthy brokers continue
independently.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.secondary_credential_quarantine")
_MARKER = "20260717-secondary-credential-quarantine-v2"
_ATTR = "_nija_secondary_credential_quarantine_v2"
_LOCK = threading.RLock()
_STARTED = False
_LOGGED = False
_FATAL_CODES = {"50100", "50101", "50111", "50112", "50113", "50119"}
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _fatal_code(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    code = str(payload.get("code", "") or "")
    return code if code in _FATAL_CODES else ""


def _is_quarantined() -> bool:
    return _truthy("NIJA_OKX_CREDENTIALS_QUARANTINED")


def _publish_quarantine(code: str, path: str) -> None:
    global _LOGGED
    os.environ["NIJA_OKX_CREDENTIALS_QUARANTINED"] = "1"
    os.environ["NIJA_OKX_CREDENTIAL_QUARANTINE_CODE"] = str(code or "50111")
    os.environ["NIJA_OKX_ACTIVATION_STATE"] = "credential_quarantined"
    os.environ["NIJA_OKX_CONNECTED"] = "0"
    os.environ["NIJA_OKX_TRADING_READY"] = "0"
    os.environ["NIJA_OKX_BALANCE_OBSERVED"] = "0"
    os.environ["NIJA_OKX_ENTRY_ISOLATED"] = "1"
    os.environ["OKX_DISABLE_ENDPOINT_FALLBACK"] = "true"
    os.environ["NIJA_OKX_RECONNECT_DISABLED"] = "1"
    if not _LOGGED:
        _LOGGED = True
        logger.critical(
            "SECONDARY_CREDENTIALS_QUARANTINED marker=%s venue=okx code=%s path=%s "
            "action=isolate_until_credentials_replaced retries_disabled=true endpoint_fallback_disabled=true",
            _MARKER,
            code,
            path,
        )


def _quarantined_payload() -> dict[str, Any]:
    return {
        "code": os.environ.get("NIJA_OKX_CREDENTIAL_QUARANTINE_CODE", "50111"),
        "msg": "credentials_quarantined",
        "data": [],
        "quarantined": True,
    }


def _patch_rest(module: ModuleType) -> bool:
    cls = getattr(module, "_OKXRestClient", None)
    current = getattr(cls, "_request", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True

    @wraps(current)
    def request(self: Any, method: str, path: str, *args: Any, **kwargs: Any):
        private = bool(kwargs.get("private", False))
        if private and (_is_quarantined() or bool(getattr(self, "_nija_credentials_quarantined", False))):
            setattr(self, "_nija_credentials_quarantined", True)
            return _quarantined_payload()
        result = current(self, method, path, *args, **kwargs)
        code = _fatal_code(result)
        if code:
            setattr(self, "_nija_credentials_quarantined", True)
            setattr(self, "_nija_credentials_quarantine_code", code)
            _publish_quarantine(code, path)
        return result

    setattr(request, _ATTR, True)
    request.__wrapped__ = current
    cls._request = request
    return True


def _disable_broker(self: Any) -> None:
    for attr, value in (
        ("connected", False),
        ("_is_available", False),
        ("trading_ready", False),
        ("_auth_failed", True),
        ("_nija_credentials_quarantined", True),
    ):
        try:
            setattr(self, attr, value)
        except Exception:
            pass


def _patch_broker(module: ModuleType) -> bool:
    cls = getattr(module, "OKXBroker", None) or getattr(module, "OKXBrokerAdapter", None)
    current = getattr(cls, "connect", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True

    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any) -> bool:
        if _is_quarantined():
            _disable_broker(self)
            return False
        clients = [getattr(self, name, None) for name in ("account_api", "market_api", "rest_client", "_rest")]
        if any(bool(getattr(client, "_nija_credentials_quarantined", False)) for client in clients if client is not None):
            _publish_quarantine(
                str(next((getattr(client, "_nija_credentials_quarantine_code", "50111") for client in clients if client is not None), "50111")),
                "connect_precheck",
            )
            _disable_broker(self)
            return False
        result = bool(current(self, *args, **kwargs))
        if _is_quarantined():
            _disable_broker(self)
            return False
        clients = [getattr(self, name, None) for name in ("account_api", "market_api", "rest_client", "_rest")]
        if any(bool(getattr(client, "_nija_credentials_quarantined", False)) for client in clients if client is not None):
            _publish_quarantine("50111", "connect_postcheck")
            _disable_broker(self)
            return False
        return result

    setattr(connect, _ATTR, True)
    connect.__wrapped__ = current
    cls.connect = connect
    return True


def _patch_loaded() -> bool:
    ready = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            ready = _patch_rest(module) or ready
            ready = _patch_broker(module) or ready
    return ready


def _watchdog() -> None:
    for _ in range(300):
        try:
            if _patch_loaded():
                os.environ["NIJA_SECONDARY_CREDENTIAL_QUARANTINE_READY"] = "1"
                return
        except Exception:
            logger.exception("SECONDARY_CREDENTIAL_QUARANTINE_RETRY marker=%s", _MARKER)
        threading.Event().wait(0.2)


def install_import_hook() -> None:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="SecondaryCredentialQuarantine", daemon=True).start()
        os.environ["NIJA_SECONDARY_CREDENTIAL_QUARANTINE_INSTALLED"] = "1"
        logger.critical("SECONDARY_CREDENTIAL_QUARANTINE_INSTALLED marker=%s process_global=true", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_fatal_code",
    "_patch_rest",
    "_patch_broker",
    "_is_quarantined",
    "_publish_quarantine",
]
