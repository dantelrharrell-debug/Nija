"""Recover Coinbase CDP credentials and publish measured funding truthfully.

The early Render liveness process starts before broker authentication and historically
reported ``coinbase_spendable_quote=0``. That value is an uninitialised placeholder,
not a balance observation. This patch keeps balance state explicitly unobserved until
Coinbase's authenticated account probe succeeds, recovers common combined-JSON CDP
credential formats, and publishes the measured spendable quote after connection.
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
_MARKER = "20260715-coinbase-funding-v1"
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_IMPORT = None
_PATCH_ATTR = "_nija_coinbase_funding_readiness_v1"


def _clean(value: Any) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    for _ in range(2):
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            text = text[1:-1].strip()
    return text


def _json_dict(value: Any) -> dict[str, Any]:
    text = _clean(value)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_value(payload: Mapping[str, Any], names: tuple[str, ...]) -> str:
    lowered = {str(key).lower(): value for key, value in payload.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return _clean(value)
    return ""


def _normalise_private_key(value: Any) -> str:
    text = _clean(value).replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    compact = re.sub(r"\s+", "", text)
    if "PRIVATEKEY" not in compact.upper() and len(compact) >= 80 and len(compact) % 4 == 0:
        try:
            decoded = base64.b64decode(compact, validate=True).decode("utf-8")
            if "PRIVATE KEY" in decoded:
                text = decoded
        except Exception:
            pass
    match = re.search(
        r"-----BEGIN (?P<label>(?:EC )?PRIVATE KEY)-----\s*(?P<body>.*?)\s*-----END (?P=label)-----",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return text.strip()
    body = re.sub(r"\s+", "", match.group("body"))
    wrapped = "\n".join(body[index:index + 64] for index in range(0, len(body), 64))
    return f"-----BEGIN {match.group('label')}-----\n{wrapped}\n-----END {match.group('label')}-----\n"


def recover_coinbase_environment() -> bool:
    """Recover key name/private key from aliases or a combined CDP JSON object."""
    aliases = (
        "COINBASE_CDP_CREDENTIALS",
        "COINBASE_CREDENTIALS_JSON",
        "COINBASE_API_CREDENTIALS",
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
        "COINBASE_PEM_CONTENT",
        "CDP_API_KEY_PRIVATE_KEY",
    )
    payload: dict[str, Any] = {}
    payload_source = "none"
    for name in aliases:
        candidate = _json_dict(os.environ.get(name))
        if candidate:
            payload = candidate
            payload_source = name
            break

    key = _first_value(payload, ("name", "apiKeyName", "api_key_name", "apiKey", "api_key", "key_name"))
    secret = _first_value(payload, ("privateKey", "private_key", "apiSecret", "api_secret", "secret", "pem", "pem_content"))

    if not key:
        for name in ("COINBASE_API_KEY", "COINBASE_PLATFORM_API_KEY", "COINBASE_CDP_API_KEY", "CDP_API_KEY_NAME"):
            value = _clean(os.environ.get(name))
            if value and not _json_dict(value):
                key = value
                break
    if not secret:
        for name in ("COINBASE_API_SECRET", "COINBASE_PEM_CONTENT", "COINBASE_PLATFORM_API_SECRET", "COINBASE_CDP_API_SECRET", "CDP_API_KEY_PRIVATE_KEY"):
            value = _clean(os.environ.get(name))
            if value and not _json_dict(value):
                secret = value
                break

    secret = _normalise_private_key(secret)
    if key:
        os.environ["COINBASE_API_KEY"] = key
    if secret:
        os.environ["COINBASE_API_SECRET"] = secret
        os.environ["COINBASE_PEM_CONTENT"] = secret

    pem_ok = bool(
        secret.startswith("-----BEGIN ")
        and "PRIVATE KEY-----" in secret
        and "-----END " in secret
        and len(secret.splitlines()) >= 3
    )
    os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
    os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "unobserved"
    logger.warning(
        "COINBASE_CREDENTIAL_RECOVERY marker=%s payload_source=%s key_present=%s pem_ok=%s pem_lines=%d funding_status=unobserved",
        _MARKER, payload_source, bool(key), pem_ok, len(secret.splitlines()),
    )
    return bool(key) and pem_ok


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0


def _spendable_from_payload(payload: Any) -> float:
    if isinstance(payload, Mapping):
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
                    total += _number(value.get("available_balance") or value.get("available") or value.get("balance") or value.get("value"))
        return total
    return _number(payload)


def _measure_spendable(broker: Any) -> float:
    for method_name in ("get_available_cash", "get_available_quote_cash", "get_cash_balance", "get_balance", "get_account_balance", "fetch_balance"):
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
    for attr in ("available_usd", "available_usdc", "cash", "balance_cache", "_balance_cache", "last_balance_payload"):
        amount = _spendable_from_payload(getattr(broker, attr, None))
        if amount > 0:
            return amount
    return 0.0


def _patch_broker_module(module: ModuleType) -> bool:
    cls = getattr(module, "CoinbaseBroker", None)
    current = getattr(cls, "connect", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def connect(self: Any, *args: Any, **kwargs: Any):
        recover_coinbase_environment()
        result = current(self, *args, **kwargs)
        connected = bool(result) or bool(getattr(self, "connected", False))
        if connected:
            spendable = _measure_spendable(self)
            os.environ["NIJA_COINBASE_CONNECTED"] = "1"
            os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "1"
            os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = f"{spendable:.8f}"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "funded" if spendable > 0 else "observed_zero"
            logger.critical(
                "COINBASE_FUNDING_MEASURED marker=%s spendable_quote=$%.2f observed=true connected=true",
                _MARKER, spendable,
            )
        else:
            os.environ["NIJA_COINBASE_CONNECTED"] = "0"
            os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
            os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
            logger.error(
                "COINBASE_AUTH_UNAVAILABLE_NOT_UNDERFUNDED marker=%s spendable_quote=unknown balance_observed=false",
                _MARKER,
            )
        return result

    setattr(connect, _PATCH_ATTR, True)
    connect.__wrapped__ = current  # type: ignore[attr-defined]
    cls.connect = connect
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.broker_manager", "broker_manager"):
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
                if name in {"bot.broker_manager", "broker_manager"}:
                    _patch_broker_module(module)
                return module
            importlib.import_module = wrapped  # type: ignore[assignment]
        _INSTALLED = True
        os.environ["NIJA_COINBASE_FUNDING_READINESS_REPAIR_INSTALLED"] = "1"
        logger.critical("COINBASE_FUNDING_READINESS_REPAIR_INSTALLED marker=%s", _MARKER)
        return True


__all__ = ["install", "recover_coinbase_environment", "_normalise_private_key", "_spendable_from_payload", "_measure_spendable"]
