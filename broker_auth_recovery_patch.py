"""Recover valid Coinbase/OKX credentials from deployment formatting and region drift.

This guard does not create credentials or bypass authentication.  It only:
* extracts Coinbase CDP key material from common JSON/escaped/base64 deployment forms;
* preserves complete PEM framing and normalizes escaped newlines;
* accepts documented environment aliases without exposing secret contents; and
* retries OKX authentication once against the alternate US/global production host
  when the configured host rejects an otherwise complete credential tuple.

A broker is considered connected only when its original connect() implementation
successfully completes the authenticated account/balance probe.
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
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.broker_auth_recovery")
_MARKER = "20260711n"
_LOCK = threading.RLock()
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED = False


def _clean(value: Any) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    for _ in range(2):
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            text = text[1:-1].strip()
    return text


def _json_value(text: str, keys: tuple[str, ...]) -> str:
    try:
        payload = json.loads(text)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value:
            return _clean(value)
    return ""


def _decode_possible_base64(text: str) -> str:
    candidate = re.sub(r"\s+", "", text)
    if len(candidate) < 80 or len(candidate) % 4:
        return text
    try:
        decoded = base64.b64decode(candidate, validate=True).decode("utf-8").strip()
    except Exception:
        return text
    return decoded if "PRIVATE KEY" in decoded else text


def _normalize_pem(value: str) -> str:
    text = _clean(value)
    extracted = _json_value(
        text,
        ("privateKey", "private_key", "apiSecret", "api_secret", "secret", "pem", "pem_content"),
    )
    if extracted:
        text = extracted
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").strip()
    text = _decode_possible_base64(text)
    text = text.replace("\\n", "\n").strip()

    match = re.search(
        r"-----BEGIN (?P<label>(?:EC )?PRIVATE KEY)-----\s*(?P<body>.*?)\s*-----END (?P=label)-----",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return text
    label = match.group("label")
    body = re.sub(r"\s+", "", match.group("body"))
    if not body:
        return text
    wrapped = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN {label}-----\n{wrapped}\n-----END {label}-----\n"


def _first_env(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = _clean(os.environ.get(name))
        if value:
            return name, value
    return "", ""


def normalize_coinbase_environment() -> bool:
    key_name, raw_key = _first_env(
        ("COINBASE_API_KEY", "COINBASE_PLATFORM_API_KEY", "COINBASE_CDP_API_KEY", "CDP_API_KEY_NAME")
    )
    secret_name, raw_secret = _first_env(
        (
            "COINBASE_API_SECRET",
            "COINBASE_PEM_CONTENT",
            "COINBASE_PLATFORM_API_SECRET",
            "COINBASE_CDP_API_SECRET",
            "CDP_API_KEY_PRIVATE_KEY",
        )
    )
    if raw_key:
        extracted_key = _json_value(raw_key, ("name", "apiKeyName", "api_key_name", "apiKey", "api_key"))
        normalized_key = extracted_key or raw_key
        os.environ["COINBASE_API_KEY"] = normalized_key.strip()
    if raw_secret:
        normalized_secret = _normalize_pem(raw_secret)
        os.environ["COINBASE_API_SECRET"] = normalized_secret
        os.environ["COINBASE_PEM_CONTENT"] = normalized_secret
    secret = os.environ.get("COINBASE_API_SECRET", "")
    pem_ok = bool(
        secret.startswith("-----BEGIN ")
        and "PRIVATE KEY-----" in secret
        and "-----END " in secret
        and len(secret.splitlines()) >= 3
    )
    logger.warning(
        "COINBASE_AUTH_NORMALIZED marker=%s key_source=%s secret_source=%s key_shape=%s pem_ok=%s pem_lines=%d",
        _MARKER,
        key_name or "missing",
        secret_name or "missing",
        "cdp" if os.environ.get("COINBASE_API_KEY", "").startswith("organizations/") else "other",
        pem_ok,
        len(secret.splitlines()),
    )
    return bool(os.environ.get("COINBASE_API_KEY")) and pem_ok


def normalize_okx_environment() -> bool:
    aliases = {
        "OKX_API_KEY": ("OKX_API_KEY", "OKX_PLATFORM_API_KEY"),
        "OKX_API_SECRET": ("OKX_API_SECRET", "OKX_PLATFORM_API_SECRET", "OKX_SECRET_KEY"),
        "OKX_PASSPHRASE": ("OKX_PASSPHRASE", "OKX_API_PASSPHRASE", "OKX_PLATFORM_PASSPHRASE"),
    }
    for canonical, names in aliases.items():
        _, value = _first_env(names)
        if value:
            os.environ[canonical] = value
    explicit = _clean(
        os.environ.get("OKX_API_BASE_URL")
        or os.environ.get("OKX_ENDPOINT")
        or os.environ.get("OKX_BASE_URL")
    ).rstrip("/")
    region = _clean(os.environ.get("OKX_REGION") or os.environ.get("OKX_ACCOUNT_REGION")).lower()
    if region in {"global", "intl", "international", "www"}:
        explicit = "https://www.okx.com"
    elif region in {"us", "usa", "united_states"}:
        explicit = "https://us.okx.com"
    if not explicit:
        explicit = "https://us.okx.com" if _clean(os.environ.get("OKX_US_REGION")).lower() in {"1", "true", "yes", "on"} else "https://www.okx.com"
    os.environ["OKX_BASE_URL"] = explicit
    complete = all(_clean(os.environ.get(k)) for k in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"))
    logger.warning(
        "OKX_AUTH_NORMALIZED marker=%s credentials_complete=%s base_url=%s region_hint=%s simulated=%s",
        _MARKER,
        complete,
        explicit,
        region or "unset",
        _clean(os.environ.get("OKX_SIMULATED_TRADING") or "false").lower(),
    )
    return complete


def _alternate_okx_url(url: str) -> str:
    normalized = _clean(url).rstrip("/")
    if normalized == "https://us.okx.com":
        return "https://www.okx.com"
    if normalized in {"https://www.okx.com", "https://openapi.okx.com"}:
        return "https://us.okx.com"
    return ""


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    if str(getattr(module, "__name__", "")) not in {"bot.broker_manager", "broker_manager"}:
        return False
    coinbase_cls = getattr(module, "CoinbaseBroker", None)
    okx_cls = getattr(module, "OKXBroker", None)

    if isinstance(coinbase_cls, type):
        original = getattr(coinbase_cls, "connect", None)
        if callable(original) and not getattr(original, "_nija_auth_recovery_20260711n", False):
            def coinbase_connect(self: Any, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> Any:
                normalize_coinbase_environment()
                return __original(self, *args, **kwargs)
            coinbase_connect._nija_auth_recovery_20260711n = True  # type: ignore[attr-defined]
            coinbase_connect.__wrapped__ = original  # type: ignore[attr-defined]
            setattr(coinbase_cls, "connect", coinbase_connect)

    if isinstance(okx_cls, type):
        original_okx = getattr(okx_cls, "connect", None)
        if callable(original_okx) and not getattr(original_okx, "_nija_auth_recovery_20260711n", False):
            def okx_connect(self: Any, *args: Any, __original: Callable[..., Any] = original_okx, **kwargs: Any) -> Any:
                normalize_okx_environment()
                primary = _clean(os.environ.get("OKX_BASE_URL")).rstrip("/")
                result = __original(self, *args, **kwargs)
                if result:
                    return result
                if _clean(os.environ.get("OKX_DISABLE_ENDPOINT_FALLBACK")).lower() in {"1", "true", "yes", "on"}:
                    return result
                alternate = _alternate_okx_url(primary)
                if not alternate:
                    return result
                logger.warning(
                    "OKX_AUTH_ENDPOINT_FALLBACK marker=%s primary=%s alternate=%s reason=primary_auth_failed",
                    _MARKER, primary, alternate,
                )
                os.environ["OKX_BASE_URL"] = alternate
                for attr, value in (("connected", False), ("client", None), ("_auth_failed", False), ("_is_available", True)):
                    try:
                        setattr(self, attr, value)
                    except Exception:
                        pass
                second = __original(self, *args, **kwargs)
                if second:
                    logger.warning("OKX_AUTH_ENDPOINT_RECOVERED marker=%s base_url=%s", _MARKER, alternate)
                    return second
                os.environ["OKX_BASE_URL"] = primary
                return second
            okx_connect._nija_auth_recovery_20260711n = True  # type: ignore[attr-defined]
            okx_connect.__wrapped__ = original_okx  # type: ignore[attr-defined]
            setattr(okx_cls, "connect", okx_connect)

    _PATCHED = True
    logger.warning("BROKER_AUTH_RECOVERY_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    return True


def _try_loaded() -> bool:
    patched = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install() -> None:
    global _ORIGINAL_IMPORT
    with _LOCK:
        normalize_coinbase_environment()
        normalize_okx_environment()
        _try_loaded()
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = importlib.import_module
        def wrapped(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT(name, package)  # type: ignore[misc]
            if name in {"bot.broker_manager", "broker_manager"}:
                _patch_module(module)
            return module
        importlib.import_module = wrapped  # type: ignore[assignment]
        logger.warning("BROKER_AUTH_RECOVERY_INSTALL_REQUESTED marker=%s", _MARKER)


def installed() -> bool:
    return _PATCHED


__all__ = [
    "install",
    "installed",
    "normalize_coinbase_environment",
    "normalize_okx_environment",
    "_normalize_pem",
    "_alternate_okx_url",
]
