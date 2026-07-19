"""Normalize Coinbase CDP credentials without quarantining a valid environment key.

The broker object can retain a stale or truncated secret while Render contains a valid
PEM.  This patch evaluates every configured secret candidate, chooses a cryptographically
valid key, synchronizes that value to the broker and environment aliases, and only
quarantines Coinbase when no usable credential exists. Kraken and OKX remain isolated.
"""
from __future__ import annotations

import base64
import builtins
import logging
import os
import re
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Optional, Tuple

logger = logging.getLogger("nija.coinbase_pem_quarantine")
_MARKER = "20260719-coinbase-pem-v2"
_PATCH_ATTR = "_nija_coinbase_pem_quarantine_v2"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()
_LAST_LOG: dict[int, float] = {}

_KEY_ENV_NAMES = (
    "COINBASE_API_KEY", "COINBASE_PLATFORM_API_KEY", "COINBASE_ADVANCED_API_KEY",
)
_SECRET_ENV_NAMES = (
    "COINBASE_API_SECRET", "COINBASE_PLATFORM_API_SECRET", "COINBASE_ADVANCED_API_SECRET",
    "COINBASE_API_PRIVATE_KEY", "COINBASE_PRIVATE_KEY",
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


def _normalize_pem(secret: str) -> str:
    text = str(secret or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    if "BEGIN" not in text:
        try:
            decoded = base64.b64decode(text, validate=True).decode("utf-8").strip()
            if "BEGIN" in decoded and "PRIVATE KEY" in decoded:
                text = decoded
        except Exception:
            pass
    match = re.search(r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----(.*?)-----END \1-----", text, re.S)
    if match:
        label = match.group(1)
        body = re.sub(r"\s+", "", match.group(2))
        if body:
            lines = [body[i:i + 64] for i in range(0, len(body), 64)]
            text = f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"
    else:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines) + ("\n" if lines else "")
    return text


def _validate_pem(secret: str) -> Tuple[bool, str]:
    normalized = _normalize_pem(secret)
    lines = normalized.splitlines()
    if not lines or "-----BEGIN " not in lines[0] or "PRIVATE KEY-----" not in lines[0]:
        return False, "pem_header_missing"
    footer = lines[-1]
    if not footer.startswith("-----END ") or "PRIVATE KEY-----" not in footer:
        return False, "pem_footer_missing"
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        load_pem_private_key(normalized.encode("utf-8"), password=None)
        return True, "pem_parse_ok"
    except Exception as exc:
        return False, f"pem_parse_failed:{type(exc).__name__}"


def _is_cdp_key(key: str, secret: str) -> bool:
    key_text = str(key or "").lower()
    secret_text = str(secret or "").upper()
    return (
        "organizations/" in key_text
        or "/apikeys/" in key_text
        or "BEGIN PRIVATE KEY" in secret_text
        or "BEGIN EC PRIVATE KEY" in secret_text
    )


def _secret_candidates(instance: Any) -> list[tuple[str, str, Optional[str]]]:
    candidates: list[tuple[str, str, Optional[str]]] = []
    # Environment is authoritative in Render and must be considered before stale object fields.
    for name in _SECRET_ENV_NAMES:
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            candidates.append((f"env:{name}", value, None))
    for attr in _SECRET_ATTRS:
        value = str(getattr(instance, attr, "") or "").strip()
        if value:
            candidates.append((f"attr:{attr}", value, attr))
    unique: list[tuple[str, str, Optional[str]]] = []
    seen: set[str] = set()
    for source, value, attr in candidates:
        fingerprint = _normalize_pem(value)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append((source, value, attr))
    return unique


def _credential_pair(instance: Any) -> Tuple[str, str, Optional[str], str]:
    key = _first_text(
        [os.environ.get(name, "") for name in _KEY_ENV_NAMES]
        + [getattr(instance, attr, "") for attr in _KEY_ATTRS]
    )
    candidates = _secret_candidates(instance)
    # For CDP credentials, choose the first cryptographically valid PEM.
    for source, value, attr in candidates:
        normalized = _normalize_pem(value)
        valid, _ = _validate_pem(normalized)
        if valid:
            return key, normalized, attr, source
    # Preserve legacy HMAC credentials when no PEM is expected.
    for source, value, attr in candidates:
        if not _is_cdp_key(key, value):
            return key, value, attr, source
    if candidates:
        source, value, attr = candidates[0]
        return key, value, attr, source
    return key, "", None, "none"


def _apply_normalized_secret(instance: Any, normalized: str) -> None:
    for attr in _SECRET_ATTRS:
        try:
            if hasattr(instance, attr) or attr in {"api_secret", "private_key"}:
                setattr(instance, attr, normalized)
        except Exception:
            pass
    for name in _SECRET_ENV_NAMES:
        if name in os.environ or name in {"COINBASE_API_SECRET", "COINBASE_API_PRIVATE_KEY"}:
            os.environ[name] = normalized
    os.environ["NIJA_COINBASE_PEM_VALID"] = "1"
    os.environ["NIJA_COINBASE_AUTH_ISOLATED"] = "0"


def _mark_quarantined(instance: Any, reason: str) -> None:
    for attr, value in (
        ("connected", False),
        ("client", None),
        ("_nija_coinbase_config_quarantined", True),
        ("_nija_coinbase_config_reason", reason),
    ):
        try:
            setattr(instance, attr, value)
        except Exception:
            pass
    os.environ["NIJA_COINBASE_PEM_VALID"] = "0"
    os.environ["NIJA_COINBASE_AUTH_ISOLATED"] = "1"
    now = time.monotonic()
    if now - _LAST_LOG.get(id(instance), 0.0) >= 300.0:
        _LAST_LOG[id(instance)] = now
        logger.error(
            "COINBASE_CREDENTIAL_QUARANTINED marker=%s reason=%s action=disable_coinbase_only kraken_unaffected=true okx_unaffected=true",
            _MARKER, reason,
        )


def _preflight(instance: Any) -> Tuple[bool, str]:
    key, secret, _, source = _credential_pair(instance)
    if not key or not secret:
        _mark_quarantined(instance, "credentials_missing")
        return False, "credentials_missing"
    if not _is_cdp_key(key, secret):
        return True, "legacy_non_pem_credential"
    normalized = _normalize_pem(secret)
    valid, reason = _validate_pem(normalized)
    if not valid:
        _mark_quarantined(instance, reason)
        return False, reason
    _apply_normalized_secret(instance, normalized)
    try:
        setattr(instance, "_nija_coinbase_config_quarantined", False)
        setattr(instance, "_nija_coinbase_config_reason", "")
    except Exception:
        pass
    logger.critical(
        "COINBASE_PEM_CANONICALIZED marker=%s source=%s parse_ok=true lines=%d",
        _MARKER, source, len(normalized.splitlines()),
    )
    return True, reason


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
        if result or bool(getattr(self, "connected", False)):
            try:
                setattr(self, "_nija_coinbase_config_quarantined", False)
                setattr(self, "_nija_coinbase_config_reason", "")
            except Exception:
                pass
            os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "ready"
            logger.critical("COINBASE_CONNECTION_RESTORED marker=%s", _MARKER)
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
                allowed, _ = _preflight(self)
                if not allowed:
                    return []
            return _original(self, *args, **kwargs)

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
