"""Canonical Coinbase credential, connection, and funding readiness.

The guard keeps Coinbase broker-local and fail-closed. It normalizes CDP credentials
from nested JSON, escaped PEM, and padded/unpadded base64 forms; patches every
Coinbase broker surface NIJA loads; and publishes spendable USD/USDC only after an
authenticated connection and balance probe succeed.
"""
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

logger = logging.getLogger("nija.coinbase_funding_readiness_repair")
_MARKER = "20260716-coinbase-connection-v2"
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_IMPORT = None
_PATCH_ATTR = "_nija_coinbase_connection_funding_v2"


def _clean(value: Any) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    for _ in range(2):
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            text = text[1:-1].strip()
    return text


def _json_dict(value: Any) -> dict[str, Any]:
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


def _first_nested(payload: Mapping[str, Any], names: tuple[str, ...]) -> str:
    targets = {name.lower() for name in names}
    for mapping in _walk(payload):
        for key, value in mapping.items():
            if str(key).lower() in targets and value:
                return _clean(value)
    return ""


def _normalise_private_key(value: Any) -> str:
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
    if not body:
        return text.strip()
    wrapped = "\n".join(body[index:index + 64] for index in range(0, len(body), 64))
    return f"-----BEGIN {match.group('label')}-----\n{wrapped}\n-----END {match.group('label')}-----\n"


def recover_coinbase_environment() -> bool:
    payload: dict[str, Any] = {}
    payload_source = "none"
    for name in (
        "COINBASE_CDP_CREDENTIALS",
        "COINBASE_CREDENTIALS_JSON",
        "COINBASE_API_CREDENTIALS",
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
        "COINBASE_PEM_CONTENT",
        "CDP_API_KEY_PRIVATE_KEY",
    ):
        candidate = _json_dict(os.environ.get(name))
        if candidate:
            payload = candidate
            payload_source = name
            break

    key = _first_nested(payload, ("name", "apiKeyName", "api_key_name", "apiKey", "api_key", "key_name"))
    secret = _first_nested(payload, ("privateKey", "private_key", "apiSecret", "api_secret", "secret", "pem", "pem_content"))

    if not key:
        for name in ("COINBASE_API_KEY", "COINBASE_PLATFORM_API_KEY", "COINBASE_CDP_API_KEY", "CDP_API_KEY_NAME"):
            value = _clean(os.environ.get(name))
            if value and not _json_dict(value):
                key = value
                break
    if not secret:
        for name in (
            "COINBASE_API_SECRET",
            "COINBASE_PEM_CONTENT",
            "COINBASE_PLATFORM_API_SECRET",
            "COINBASE_CDP_API_SECRET",
            "CDP_API_KEY_PRIVATE_KEY",
        ):
            value = _clean(os.environ.get(name))
            if value and not _json_dict(value):
                secret = value
                break

    secret = _normalise_private_key(secret)
    if key:
        for name in ("COINBASE_API_KEY", "COINBASE_PLATFORM_API_KEY"):
            os.environ[name] = key
    if secret:
        for name in ("COINBASE_API_SECRET", "COINBASE_PLATFORM_API_SECRET", "COINBASE_PEM_CONTENT"):
            os.environ[name] = secret

    pem_ok = bool(
        secret.startswith("-----BEGIN ")
        and "PRIVATE KEY-----" in secret
        and "-----END " in secret
        and len(secret.splitlines()) >= 3
    )
    ready = bool(key) and pem_ok
    os.environ["NIJA_COINBASE_CREDENTIALS_NORMALIZED"] = "1" if ready else "0"
    os.environ.setdefault("NIJA_COINBASE_BALANCE_OBSERVED", "0")
    os.environ.setdefault("NIJA_COINBASE_FUNDING_STATUS", "unobserved")
    logger.warning(
        "COINBASE_CREDENTIAL_RECOVERY marker=%s payload_source=%s key_present=%s key_shape=%s pem_ok=%s pem_lines=%d funding_status=%s",
        _MARKER,
        payload_source,
        bool(key),
        "cdp" if key.startswith("organizations/") else "other",
        pem_ok,
        len(secret.splitlines()),
        os.environ.get("NIJA_COINBASE_FUNDING_STATUS", "unobserved"),
    )
    return ready


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0


def _spendable_from_payload(payload: Any) -> float:
    if not isinstance(payload, Mapping):
        return _number(payload)
    total = 0.0
    for key, value in payload.items():
        name = str(key).lower()
        if name in {"usd", "usdc", "cash", "available_usd", "available_usdc", "spendable", "available", "available_balance"}:
            if isinstance(value, Mapping):
                total += _number(value.get("value") or value.get("amount") or value.get("balance"))
            else:
                total += _number(value)
        elif isinstance(value, Mapping):
            currency = str(value.get("currency") or value.get("asset") or "").upper()
            if currency in {"USD", "USDC"}:
                nested = value.get("available_balance") or value.get("available") or value.get("balance") or value.get("value")
                if isinstance(nested, Mapping):
                    nested = nested.get("value") or nested.get("amount")
                total += _number(nested)
        elif isinstance(value, list):
            total += sum(_spendable_from_payload(item) for item in value)
    return total


def _measure_spendable(broker: Any) -> float:
    for method_name in ("get_available_cash", "get_available_quote_cash", "get_cash_balance", "get_balance", "get_account_balance", "fetch_balance", "get_accounts"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        for args in (("USD",), tuple()):
            try:
                amount = _spendable_from_payload(method(*args))
                if amount > 0:
                    return amount
            except TypeError:
                continue
            except Exception:
                break
    for attr in ("available_usd", "available_usdc", "cash", "balance_cache", "_balance_cache", "last_balance_payload", "accounts"):
        amount = _spendable_from_payload(getattr(broker, attr, None))
        if amount > 0:
            return amount
    return 0.0


def _connect_wrapper(cls: type, current):
    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any):
        if not recover_coinbase_environment():
            try:
                self.connected = False
            except Exception:
                pass
            os.environ["NIJA_COINBASE_CONNECTED"] = "0"
            os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
            logger.error("COINBASE_CONNECTION_BLOCKED_INVALID_CREDENTIAL_FORMAT marker=%s class=%s", _MARKER, cls.__name__)
            return False
        try:
            result = current(self, *args, **kwargs)
        except Exception as exc:
            try:
                self.connected = False
            except Exception:
                pass
            os.environ["NIJA_COINBASE_CONNECTED"] = "0"
            os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
            logger.error(
                "COINBASE_CONNECTION_AUTH_FAILED marker=%s class=%s error_type=%s error=%s",
                _MARKER,
                cls.__name__,
                type(exc).__name__,
                str(exc)[:240],
            )
            return False
        connected = bool(result) or bool(getattr(self, "connected", False))
        os.environ["NIJA_COINBASE_CONNECTED"] = "1" if connected else "0"
        if connected:
            spendable = _measure_spendable(self)
            os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "1"
            os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = f"{spendable:.8f}"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "funded" if spendable > 0 else "observed_zero"
            logger.critical(
                "COINBASE_CONNECTION_RECOVERED marker=%s class=%s connected=true spendable_quote=$%.2f",
                _MARKER,
                cls.__name__,
                spendable,
            )
        else:
            os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
            logger.error("COINBASE_CONNECTION_PROBE_FAILED marker=%s class=%s", _MARKER, cls.__name__)
        return result

    setattr(connect, _PATCH_ATTR, True)
    connect.__wrapped__ = current  # type: ignore[attr-defined]
    return connect


def _patch_broker_module(module: ModuleType) -> bool:
    changed = False
    for name in ("CoinbaseBroker", "CoinbaseBrokerAdapter", "_CoinbaseInvalidProductFilter"):
        cls = getattr(module, name, None)
        current = getattr(cls, "connect", None) if isinstance(cls, type) else None
        if not callable(current):
            continue
        if getattr(current, _PATCH_ATTR, False):
            changed = True
            continue
        cls.connect = _connect_wrapper(cls, current)
        changed = True
        logger.warning("COINBASE_CONNECTION_SURFACE_PATCHED marker=%s module=%s class=%s", _MARKER, getattr(module, "__name__", "unknown"), name)
    return changed


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_broker_module(module) or changed
    return changed


def install() -> bool:
    global _INSTALLED, _ORIGINAL_IMPORT
    with _LOCK:
        recover_coinbase_environment()
        try:
            auth = importlib.import_module("broker_auth_recovery_patch")
            auth.normalize_coinbase_environment = recover_coinbase_environment
        except Exception:
            pass
        _patch_loaded()
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = importlib.import_module
            def wrapped(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT(name, package)  # type: ignore[misc]
                if name in {"bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"}:
                    _patch_broker_module(module)
                return module
            importlib.import_module = wrapped  # type: ignore[assignment]
        _INSTALLED = True
        os.environ["NIJA_COINBASE_FUNDING_READINESS_REPAIR_INSTALLED"] = "1"
        os.environ["NIJA_COINBASE_CONNECTION_CONVERGENCE_INSTALLED"] = "1"
        logger.critical("COINBASE_CONNECTION_CONVERGENCE_INSTALLED marker=%s", _MARKER)
        return True


__all__ = [
    "install",
    "recover_coinbase_environment",
    "_normalise_private_key",
    "_spendable_from_payload",
    "_measure_spendable",
]
