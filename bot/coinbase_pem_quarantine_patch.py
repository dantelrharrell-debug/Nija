"""Normalize or quarantine malformed Coinbase Advanced Trade PEM credentials.

A malformed CDP private key previously reached the Coinbase SDK on every market
refresh, producing repeated ``MalformedFraming`` errors.  This patch repairs the
common literal-``\\n`` formatting problem.  If the exact credential still cannot
be parsed, Coinbase is marked configuration-failed and all product/balance
surfaces fail quietly and deterministically while Kraken remains independent.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Optional, Tuple

logger = logging.getLogger("nija.coinbase_pem_quarantine")
_MARKER = "20260713-coinbase-pem-v1"
_PATCH_ATTR = "_nija_coinbase_pem_quarantine_v1"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()
_LAST_LOG: dict[int, float] = {}

_KEY_ENV_NAMES = (
    "COINBASE_PLATFORM_API_KEY", "COINBASE_API_KEY", "COINBASE_ADVANCED_API_KEY",
)
_SECRET_ENV_NAMES = (
    "COINBASE_PLATFORM_API_SECRET", "COINBASE_API_SECRET", "COINBASE_ADVANCED_API_SECRET",
    "COINBASE_PRIVATE_KEY",
)
_SECRET_ATTRS = ("api_secret", "secret", "private_key", "api_key_secret", "coinbase_api_secret")
_KEY_ATTRS = ("api_key", "key", "api_key_name", "coinbase_api_key")
_PRODUCT_METHODS = (
    "get_all_products", "get_products", "list_products", "fetch_products",
    "get_available_markets", "get_tradable_symbols",
)


def _first_text(values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _credential_pair(instance: Any) -> Tuple[str, str, Optional[str]]:
    key = _first_text([getattr(instance, attr, "") for attr in _KEY_ATTRS] + [os.environ.get(name, "") for name in _KEY_ENV_NAMES])
    secret_attr: Optional[str] = None
    secret = ""
    for attr in _SECRET_ATTRS:
        value = str(getattr(instance, attr, "") or "").strip()
        if value:
            secret, secret_attr = value, attr
            break
    if not secret:
        secret = _first_text(os.environ.get(name, "") for name in _SECRET_ENV_NAMES)
    return key, secret, secret_attr


def _is_cdp_key(key: str, secret: str) -> bool:
    key_text = str(key or "").lower()
    secret_text = str(secret or "").upper()
    return (
        "organizations/" in key_text
        or "/apikeys/" in key_text
        or "BEGIN PRIVATE KEY" in secret_text
        or "BEGIN EC PRIVATE KEY" in secret_text
    )


def _normalize_pem(secret: str) -> str:
    text = str(secret or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


def _validate_pem(secret: str) -> Tuple[bool, str]:
    normalized = _normalize_pem(secret)
    if "-----BEGIN " not in normalized or " PRIVATE KEY-----" not in normalized:
        return False, "pem_header_missing"
    if "-----END " not in normalized or " PRIVATE KEY-----" not in normalized.rsplit("-----END ", 1)[-1]:
        return False, "pem_footer_missing"
    try:
        from cryptography.hazmat.primitives import serialization
        serialization.load_pem_private_key(normalized.encode("utf-8"), password=None)
        return True, "pem_parse_ok"
    except Exception as exc:
        return False, f"pem_parse_failed:{type(exc).__name__}"


def _apply_normalized_secret(instance: Any, normalized: str, secret_attr: Optional[str]) -> None:
    if secret_attr:
        try:
            setattr(instance, secret_attr, normalized)
        except Exception:
            pass
    for name in _SECRET_ENV_NAMES:
        if str(os.environ.get(name, "") or "").strip():
            os.environ[name] = normalized


def _mark_quarantined(instance: Any, reason: str) -> None:
    for attr, value in (
        ("connected", False),
        ("client", None),
        ("_nija_coinbase_config_quarantined", True),
        ("_nija_coinbase_config_reason", reason),
        ("_last_known_balance", 0.0),
    ):
        try:
            setattr(instance, attr, value)
        except Exception:
            pass
    now = time.monotonic()
    if now - _LAST_LOG.get(id(instance), 0.0) >= 300.0:
        _LAST_LOG[id(instance)] = now
        logger.error(
            "COINBASE_CREDENTIAL_QUARANTINED marker=%s reason=%s action=disable_coinbase_only kraken_unaffected=true",
            _MARKER, reason,
        )


def _preflight(instance: Any) -> Tuple[bool, str]:
    key, secret, secret_attr = _credential_pair(instance)
    if not key or not secret:
        return False, "credentials_missing"
    if not _is_cdp_key(key, secret):
        return True, "legacy_non_pem_credential"
    normalized = _normalize_pem(secret)
    valid, reason = _validate_pem(normalized)
    if valid:
        _apply_normalized_secret(instance, normalized, secret_attr)
        try:
            setattr(instance, "_nija_coinbase_config_quarantined", False)
            setattr(instance, "_nija_coinbase_config_reason", "")
        except Exception:
            pass
        logger.info("COINBASE_PEM_NORMALIZED marker=%s parse_ok=true", _MARKER)
        return True, reason
    _mark_quarantined(instance, reason)
    return False, reason


def _empty_for(method_name: str):
    if method_name in {"get_available_markets", "get_tradable_symbols"}:
        return []
    return []


def _patch_class(cls: type) -> bool:
    current_connect = getattr(cls, "connect", None)
    if not callable(current_connect) or getattr(current_connect, _PATCH_ATTR, False):
        return False
    original_connect = current_connect

    @wraps(original_connect)
    def connect(self: Any, *args: Any, **kwargs: Any):
        allowed, reason = _preflight(self)
        if not allowed:
            logger.warning("COINBASE_CONNECT_SKIPPED marker=%s reason=%s", _MARKER, reason)
            return False
        try:
            result = original_connect(self, *args, **kwargs)
        except Exception as exc:
            text = str(exc).lower()
            if any(token in text for token in ("malformedframing", "unable to load pem", "private key")):
                _mark_quarantined(self, f"sdk_rejected_pem:{type(exc).__name__}")
                return False
            raise
        if not result and getattr(self, "_nija_coinbase_config_quarantined", False):
            return False
        return result

    setattr(connect, _PATCH_ATTR, True)
    setattr(connect, "__wrapped__", original_connect)
    setattr(cls, "connect", connect)

    for method_name in _PRODUCT_METHODS:
        current = getattr(cls, method_name, None)
        if not callable(current) or getattr(current, _PATCH_ATTR, False):
            continue

        def guarded(self: Any, *args: Any, _original=current, _name=method_name, **kwargs: Any):
            if getattr(self, "_nija_coinbase_config_quarantined", False):
                _mark_quarantined(self, str(getattr(self, "_nija_coinbase_config_reason", "invalid_pem")))
                return _empty_for(_name)
            try:
                return _original(self, *args, **kwargs)
            except Exception as exc:
                text = str(exc).lower()
                if any(token in text for token in ("malformedframing", "unable to load pem", "private key")):
                    _mark_quarantined(self, f"sdk_rejected_pem:{type(exc).__name__}")
                    return _empty_for(_name)
                raise

        setattr(guarded, _PATCH_ATTR, True)
        setattr(guarded, "__wrapped__", current)
        setattr(cls, method_name, guarded)

    logger.warning("COINBASE_PEM_QUARANTINE_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    changed = False
    for name in dir(module):
        cls = getattr(module, name, None)
        if isinstance(cls, type) and "coinbase" in name.lower():
            changed = _patch_class(cls) or changed
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> None:
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType) and str(getattr(module, "__name__", "")).endswith(("broker_manager", "broker_integration")):
            try:
                _patch_module(module)
            except Exception:
                continue


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = builtins.__import__
        local = threading.local()

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            if getattr(local, "active", False):
                return module
            local.active = True
            try:
                _patch_loaded()
            finally:
                local.active = False
            return module

        builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    logger.critical("COINBASE_PEM_QUARANTINE_INSTALLED marker=%s", _MARKER)


__all__ = ["install_import_hook", "_normalize_pem", "_validate_pem", "_preflight", "_patch_class"]
