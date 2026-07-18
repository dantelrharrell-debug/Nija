"""Quarantine OKX after definitive credential rejection.

The quarantine is venue-local. It never changes Coinbase/Kraken connection,
readiness, execution authority, or trading state. Regional endpoint selection
is installed before OKX private requests are patched.
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
_MARKER = "20260718-secondary-credential-quarantine-v4"
_ATTR = "_nija_secondary_credential_quarantine_v4"
_LOCK = threading.RLock()
_STARTED = False
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
    # OKX-only state. Do not mutate global execution authority or other venues.
    values = {
        "NIJA_OKX_CREDENTIALS_QUARANTINED": "1",
        "NIJA_OKX_CREDENTIAL_QUARANTINE_CODE": str(code or "50111"),
        "NIJA_OKX_ACTIVATION_STATE": "credential_quarantined",
        "NIJA_OKX_CONNECTED": "0",
        "NIJA_OKX_TRADING_READY": "0",
        "NIJA_OKX_BALANCE_OBSERVED": "0",
        "NIJA_OKX_ENTRY_ISOLATED": "1",
        "OKX_DISABLE_ENDPOINT_FALLBACK": "true",
        "NIJA_OKX_RECONNECT_DISABLED": "1",
    }
    os.environ.update(values)
    if not _truthy("NIJA_OKX_QUARANTINE_LOGGED"):
        os.environ["NIJA_OKX_QUARANTINE_LOGGED"] = "1"
        logger.critical(
            "SECONDARY_CREDENTIALS_QUARANTINED marker=%s venue=okx code=%s path=%s "
            "scope=okx_only coinbase_affected=false kraken_affected=false retries_disabled=true",
            _MARKER, code, path,
        )


def _quarantined_payload() -> dict[str, Any]:
    return {
        "code": os.environ.get("NIJA_OKX_CREDENTIAL_QUARANTINE_CODE", "50111"),
        "msg": "credentials_quarantined",
        "data": [],
        "quarantined": True,
        "venue": "okx",
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
        ("connected", False), ("_is_available", False), ("trading_ready", False),
        ("_auth_failed", True), ("_nija_credentials_quarantined", True),
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
        bad = next((c for c in clients if c is not None and bool(getattr(c, "_nija_credentials_quarantined", False))), None)
        if bad is not None:
            _publish_quarantine(str(getattr(bad, "_nija_credentials_quarantine_code", "50111")), "connect_precheck")
            _disable_broker(self)
            return False
        result = bool(current(self, *args, **kwargs))
        if _is_quarantined():
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
        # Endpoint choice must be resolved before any authenticated OKX call.
        from bot.okx_regional_endpoint_isolation_patch import install as install_endpoint
        install_endpoint()
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="SecondaryCredentialQuarantine", daemon=True).start()
        os.environ["NIJA_SECONDARY_CREDENTIAL_QUARANTINE_INSTALLED"] = "1"
        if not _truthy("NIJA_SECONDARY_CREDENTIAL_QUARANTINE_INSTALL_LOGGED"):
            os.environ["NIJA_SECONDARY_CREDENTIAL_QUARANTINE_INSTALL_LOGGED"] = "1"
            logger.critical("SECONDARY_CREDENTIAL_QUARANTINE_INSTALLED marker=%s scope=okx_only", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = [
    "install", "install_import_hook", "_fatal_code", "_patch_rest", "_patch_broker",
    "_is_quarantined", "_publish_quarantine", "_quarantined_payload",
]
