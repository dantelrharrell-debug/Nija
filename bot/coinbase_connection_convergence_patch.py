"""Canonical Coinbase credential and connection convergence."""
from __future__ import annotations

import base64
import importlib
import json
import logging
import os
import re
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.coinbase_connection_convergence")
MARKER = "20260716-coinbase-connection-v2"
_LOCK = threading.RLock()
_ORIGINAL_IMPORT = None
_PATCH_ATTR = "_nija_coinbase_connection_convergence_v2"


def _clean(value: Any) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    for _ in range(2):
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            text = text[1:-1].strip()
    return text


def _parse_json(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(_clean(value))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _find_nested(payload: Mapping[str, Any], names: tuple[str, ...]) -> str:
    targets = {name.lower() for name in names}
    for mapping in _walk(payload):
        for key, value in mapping.items():
            if str(key).lower() in targets and value:
                return _clean(value)
    return ""


def _decode_private_key(value: Any) -> str:
    text = _clean(value).replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    if "PRIVATE KEY" not in text.upper():
        compact = re.sub(r"\s+", "", text)
        padded = compact + ("=" * ((4 - len(compact) % 4) % 4))
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = decoder(padded.encode("ascii")).decode("utf-8").strip()
            except Exception:
                continue
            if "PRIVATE KEY" in decoded.upper():
                text = decoded
                break
    match = re.search(
        r"-----BEGIN (?P<label>(?:EC )?PRIVATE KEY)-----\s*(?P<body>.*?)\s*-----END (?P=label)-----",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return text.strip()
    body = re.sub(r"\s+", "", match.group("body"))
    wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN {match.group('label')}-----\n{wrapped}\n-----END {match.group('label')}-----\n"


def normalize_environment() -> bool:
    payload: dict[str, Any] = {}
    source = "none"
    for name in (
        "COINBASE_CDP_CREDENTIALS", "COINBASE_CREDENTIALS_JSON", "COINBASE_API_CREDENTIALS",
        "COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_PEM_CONTENT",
    ):
        candidate = _parse_json(os.environ.get(name))
        if candidate:
            payload, source = candidate, name
            break
    key = _find_nested(payload, ("name", "apiKeyName", "api_key_name", "key_name", "apiKey", "api_key"))
    secret = _find_nested(payload, ("privateKey", "private_key", "apiSecret", "api_secret", "secret", "pem", "pem_content"))
    if not key:
        for name in ("COINBASE_API_KEY", "COINBASE_PLATFORM_API_KEY", "COINBASE_CDP_API_KEY", "CDP_API_KEY_NAME"):
            value = _clean(os.environ.get(name))
            if value and not _parse_json(value):
                key = value
                break
    if not secret:
        for name in ("COINBASE_API_SECRET", "COINBASE_PEM_CONTENT", "COINBASE_PLATFORM_API_SECRET", "COINBASE_CDP_API_SECRET", "CDP_API_KEY_PRIVATE_KEY"):
            value = _clean(os.environ.get(name))
            if value and not _parse_json(value):
                secret = value
                break
    secret = _decode_private_key(secret)
    if key:
        os.environ["COINBASE_API_KEY"] = key
        os.environ["COINBASE_PLATFORM_API_KEY"] = key
    if secret:
        for name in ("COINBASE_API_SECRET", "COINBASE_PLATFORM_API_SECRET", "COINBASE_PEM_CONTENT"):
            os.environ[name] = secret
    pem_ok = bool(secret.startswith("-----BEGIN ") and "PRIVATE KEY-----" in secret and "-----END " in secret and len(secret.splitlines()) >= 3)
    ready = bool(key) and pem_ok
    os.environ["NIJA_COINBASE_CREDENTIALS_NORMALIZED"] = "1" if ready else "0"
    logger.warning("COINBASE_CONNECTION_CREDENTIALS_NORMALIZED marker=%s source=%s key_present=%s key_shape=%s pem_ok=%s pem_lines=%d", MARKER, source, bool(key), "cdp" if key.startswith("organizations/") else "other", pem_ok, len(secret.splitlines()))
    return ready


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "connect", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any):
        if not normalize_environment():
            self.connected = False
            os.environ["NIJA_COINBASE_CONNECTED"] = "0"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
            logger.error("COINBASE_CONNECTION_BLOCKED_INVALID_CREDENTIAL_FORMAT marker=%s class=%s", MARKER, cls.__name__)
            return False
        try:
            result = current(self, *args, **kwargs)
        except Exception as exc:
            self.connected = False
            os.environ["NIJA_COINBASE_CONNECTED"] = "0"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
            logger.error("COINBASE_CONNECTION_AUTH_FAILED marker=%s class=%s error_type=%s error=%s", MARKER, cls.__name__, type(exc).__name__, str(exc)[:240])
            return False
        connected = bool(result) or bool(getattr(self, "connected", False))
        os.environ["NIJA_COINBASE_CONNECTED"] = "1" if connected else "0"
        if connected:
            logger.critical("COINBASE_CONNECTION_RECOVERED marker=%s class=%s connected=true", MARKER, cls.__name__)
        else:
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
            logger.error("COINBASE_CONNECTION_PROBE_FAILED marker=%s class=%s", MARKER, cls.__name__)
        return result

    setattr(connect, _PATCH_ATTR, True)
    connect.__wrapped__ = current  # type: ignore[attr-defined]
    cls.connect = connect
    return True


def _patch_module(module: ModuleType) -> bool:
    changed = False
    for name in ("CoinbaseBroker", "CoinbaseBrokerAdapter", "_CoinbaseInvalidProductFilter"):
        cls = getattr(module, name, None)
        if isinstance(cls, type):
            changed = _patch_class(cls) or changed
    return changed


def install() -> bool:
    global _ORIGINAL_IMPORT
    with _LOCK:
        normalize_environment()
        for module_name, attr in (("broker_auth_recovery_patch", "normalize_coinbase_environment"), ("bot.coinbase_funding_readiness_repair_patch", "recover_coinbase_environment")):
            try:
                setattr(importlib.import_module(module_name), attr, normalize_environment)
            except Exception:
                pass
        for name in ("bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"):
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                _patch_module(module)
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = importlib.import_module
            def wrapped(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT(name, package)  # type: ignore[misc]
                if name in {"bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"}:
                    _patch_module(module)
                return module
            importlib.import_module = wrapped  # type: ignore[assignment]
        os.environ["NIJA_COINBASE_CONNECTION_CONVERGENCE_INSTALLED"] = "1"
        logger.critical("COINBASE_CONNECTION_CONVERGENCE_INSTALLED marker=%s", MARKER)
        return True


__all__ = ["install", "normalize_environment", "_decode_private_key", "_find_nested"]
