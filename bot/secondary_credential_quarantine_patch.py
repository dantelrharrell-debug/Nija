"""Quarantine secondary venues after definitive credential rejection.

A 50111/50119/50112 response cannot be repaired by retrying. Repeated activation
attempts only spam logs and consume API calls. The affected venue is isolated while
healthy brokers remain independently executable.
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
_MARKER = "20260715-secondary-credential-quarantine-v1"
_ATTR = "_nija_secondary_credential_quarantine_v1"
_LOCK = threading.RLock()
_STARTED = False
_FATAL_CODES = {"50100", "50101", "50111", "50112", "50113", "50119"}


def _fatal_code(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    code = str(payload.get("code", "") or "")
    return code if code in _FATAL_CODES else ""


def _patch_rest(module: ModuleType) -> bool:
    cls = getattr(module, "_OKXRestClient", None)
    current = getattr(cls, "_request", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True

    @wraps(current)
    def request(self: Any, method: str, path: str, *args: Any, **kwargs: Any):
        if bool(getattr(self, "_nija_credentials_quarantined", False)) and kwargs.get("private", False):
            return {
                "code": str(getattr(self, "_nija_credentials_quarantine_code", "50111")),
                "msg": "credentials_quarantined",
                "data": [],
                "quarantined": True,
            }
        result = current(self, method, path, *args, **kwargs)
        code = _fatal_code(result)
        if code:
            setattr(self, "_nija_credentials_quarantined", True)
            setattr(self, "_nija_credentials_quarantine_code", code)
            os.environ["NIJA_OKX_CREDENTIALS_QUARANTINED"] = "1"
            os.environ["NIJA_OKX_ACTIVATION_STATE"] = "credential_quarantined"
            os.environ["NIJA_OKX_CONNECTED"] = "0"
            os.environ["NIJA_OKX_TRADING_READY"] = "0"
            logger.critical(
                "SECONDARY_CREDENTIALS_QUARANTINED marker=%s venue=okx code=%s path=%s action=isolate_until_credentials_replaced",
                _MARKER, code, path,
            )
        return result

    setattr(request, _ATTR, True)
    request.__wrapped__ = current
    cls._request = request
    return True


def _patch_broker(module: ModuleType) -> bool:
    cls = getattr(module, "OKXBroker", None) or getattr(module, "OKXBrokerAdapter", None)
    current = getattr(cls, "connect", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True

    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any) -> bool:
        clients = [getattr(self, name, None) for name in ("account_api", "market_api", "rest_client", "_rest")]
        if any(bool(getattr(client, "_nija_credentials_quarantined", False)) for client in clients if client is not None):
            setattr(self, "connected", False)
            setattr(self, "_is_available", False)
            return False
        result = bool(current(self, *args, **kwargs))
        clients = [getattr(self, name, None) for name in ("account_api", "market_api", "rest_client", "_rest")]
        if any(bool(getattr(client, "_nija_credentials_quarantined", False)) for client in clients if client is not None):
            setattr(self, "connected", False)
            setattr(self, "_is_available", False)
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
    while True:
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
        logger.critical("SECONDARY_CREDENTIAL_QUARANTINE_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = ["install", "install_import_hook", "_fatal_code", "_patch_rest", "_patch_broker"]
