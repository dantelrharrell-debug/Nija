"""Normalize secondary-venue credentials and expose fail-closed diagnostics."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger("nija.secondary_venue_runtime_diagnostics")
_MARKER = "20260723-secondary-runtime-diagnostics-v5"
_INSTALLED = False
_LOCK = threading.RLock()
_LAST_LOG: dict[str, float] = {}
_COINBASE_SECRET_ALIASES = (
    "COINBASE_API_SECRET",
    "COINBASE_PLATFORM_API_SECRET",
    "COINBASE_ADVANCED_API_SECRET",
    "COINBASE_PEM_CONTENT",
    "COINBASE_API_PRIVATE_KEY",
    "COINBASE_PRIVATE_KEY",
)
_COINBASE_KEY_ALIASES = (
    "COINBASE_API_KEY",
    "COINBASE_PLATFORM_API_KEY",
    "COINBASE_ADVANCED_API_KEY",
)


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _extract_json_secret(value: str) -> str:
    try:
        payload = json.loads(value)
    except Exception:
        return value
    if not isinstance(payload, dict):
        return value
    lowered = {str(key).lower(): item for key, item in payload.items()}
    for key in (
        "privatekey",
        "private_key",
        "apisecret",
        "api_secret",
        "secret",
        "pem",
        "pem_content",
    ):
        candidate = lowered.get(key)
        if candidate:
            return str(candidate)
    return value


def _decode_possible_base64(value: str) -> str:
    candidate = re.sub(r"\s+", "", value)
    if len(candidate) < 80 or len(candidate) % 4:
        return value
    try:
        decoded = base64.b64decode(candidate, validate=True).decode("utf-8").strip()
    except Exception:
        return value
    return decoded if "PRIVATE KEY" in decoded else value


def normalize_coinbase_private_key(value: str) -> str:
    """Return a canonical PEM from supported secret-manager encodings."""

    text = _strip_outer_quotes(str(value or ""))
    text = _extract_json_secret(text)
    text = _strip_outer_quotes(text)
    text = (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )
    text = _decode_possible_base64(text).replace("\\n", "\n").strip()
    match = re.search(
        r"-----BEGIN (?P<label>(?:EC )?PRIVATE KEY)-----\s*(?P<body>.*?)\s*-----END (?P=label)-----",
        text,
        flags=re.DOTALL,
    )
    if match:
        label = match.group("label")
        body = re.sub(r"\s+", "", match.group("body"))
        if body:
            wrapped = "\n".join(
                body[index : index + 64] for index in range(0, len(body), 64)
            )
            return f"-----BEGIN {label}-----\n{wrapped}\n-----END {label}-----\n"
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


def _validate_coinbase_key(secret: str) -> tuple[bool, str]:
    """Validate key material and return a non-sensitive category."""

    if not secret:
        return False, "missing"
    if "-----BEGIN" not in secret or "PRIVATE KEY-----" not in secret:
        return False, "missing_pem_header"
    try:
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(secret.encode("utf-8"), password=None)
        curve = getattr(getattr(key, "curve", None), "name", "unknown")
        if curve not in {"secp256r1", "prime256v1"}:
            return False, "unsupported_curve"
    except Exception:
        if (
            os.environ.get("NIJA_COINBASE_CONNECTED") == "1"
            and os.environ.get("NIJA_COINBASE_TRADING_READY") == "1"
        ):
            return True, "authenticated_connection"
        return False, "parse_failed"
    return True, "valid_es256"


def _coinbase_pem_expected(candidates: list[tuple[str, str]]) -> bool:
    key_text = " ".join(
        str(os.environ.get(name, "") or "") for name in _COINBASE_KEY_ALIASES
    ).lower()
    if "organizations/" in key_text or "/apikeys/" in key_text:
        return True
    return any(
        "PRIVATE KEY" in raw.upper() or "PRIVATEKEY" in raw.upper()
        for _, raw in candidates
    )


def _quarantine_coinbase() -> None:
    """Isolate an invalid optional Coinbase venue without retaining secret details."""

    os.environ["NIJA_COINBASE_PEM_STATE"] = "invalid"
    os.environ["NIJA_COINBASE_PEM_VALID"] = "0"
    os.environ["NIJA_COINBASE_PEM_QUARANTINED"] = "1"
    os.environ["NIJA_COINBASE_PEM_INVALID_REASON"] = "validation_failed"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "quarantined_invalid_pem"
    os.environ["NIJA_COINBASE_CONNECTED"] = "0"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
    os.environ["NIJA_DISABLE_COINBASE"] = "true"
    os.environ["ENABLE_COINBASE_TRADING"] = "false"
    os.environ["COINBASE_LIVE_TRADING_ENABLED"] = "false"
    logger.critical(
        "COINBASE_PEM_QUARANTINED marker=%s "
        "reason=validation_failed kraken_and_okx_remain_independent=true",
        _MARKER,
    )


def _restore_coinbase_quarantine_state() -> None:
    """Keep the explicit quarantine state visible after generic activation skips."""

    if os.environ.get("NIJA_COINBASE_PEM_QUARANTINED") != "1":
        return
    os.environ["NIJA_COINBASE_PEM_STATE"] = "invalid"
    os.environ["NIJA_COINBASE_PEM_VALID"] = "0"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "quarantined_invalid_pem"
    os.environ["NIJA_COINBASE_CONNECTED"] = "0"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
    os.environ["NIJA_DISABLE_COINBASE"] = "true"
    os.environ["ENABLE_COINBASE_TRADING"] = "false"
    os.environ["COINBASE_LIVE_TRADING_ENABLED"] = "false"


def _normalize_coinbase_env() -> None:
    candidates = [
        (name, str(os.environ.get(name, "") or "").strip())
        for name in _COINBASE_SECRET_ALIASES
        if str(os.environ.get(name, "") or "").strip()
    ]
    if not candidates:
        os.environ["NIJA_COINBASE_PEM_STATE"] = "missing"
        os.environ["NIJA_COINBASE_PEM_VALID"] = "0"
        os.environ["NIJA_COINBASE_CONNECTED"] = "0"
        os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
        logger.error("COINBASE_PEM_INVALID marker=%s reason=missing_secret", _MARKER)
        return

    selected_secret = ""
    for _source, raw in candidates:
        normalized = normalize_coinbase_private_key(raw)
        valid, _category = _validate_coinbase_key(normalized)
        if valid:
            selected_secret = normalized
            break

    if selected_secret:
        for name in _COINBASE_SECRET_ALIASES:
            os.environ[name] = selected_secret
        os.environ["NIJA_COINBASE_PEM_STATE"] = "valid"
        os.environ["NIJA_COINBASE_PEM_VALID"] = "1"
        os.environ["NIJA_COINBASE_PEM_QUARANTINED"] = "0"
        os.environ.pop("NIJA_COINBASE_PEM_INVALID_REASON", None)
        logger.warning(
            "COINBASE_PEM_CANONICALIZED marker=%s validation=es256",
            _MARKER,
        )
        return

    if not _coinbase_pem_expected(candidates):
        os.environ["NIJA_COINBASE_PEM_STATE"] = "legacy_unverified"
        os.environ["NIJA_COINBASE_PEM_VALID"] = "0"
        logger.warning(
            "COINBASE_PEM_NOT_REQUIRED marker=%s credential_mode=legacy",
            _MARKER,
        )
        return

    os.environ["NIJA_COINBASE_PEM_STATE"] = "invalid"
    os.environ["NIJA_COINBASE_PEM_VALID"] = "0"
    logger.error(
        "COINBASE_PEM_INVALID marker=%s reason=validation_failed "
        "action=quarantine_coinbase_only",
        _MARKER,
    )
    _quarantine_coinbase()


def _log_state(venue: str, *, force: bool = False) -> None:
    now = time.monotonic()
    if not force and now - _LAST_LOG.get(venue, 0.0) < 30.0:
        return
    _LAST_LOG[venue] = now
    upper = venue.upper()
    pem = (
        os.environ.get("NIJA_COINBASE_PEM_STATE", "n/a")
        if venue == "coinbase"
        else "n/a"
    )
    if (
        venue == "coinbase"
        and os.environ.get("NIJA_COINBASE_CONNECTED") == "1"
        and os.environ.get("NIJA_COINBASE_TRADING_READY") == "1"
    ):
        pem = "valid"
        os.environ["NIJA_COINBASE_PEM_STATE"] = "valid"
        os.environ["NIJA_COINBASE_PEM_VALID"] = "1"
    logger.warning(
        "SECONDARY_VENUE_RUNTIME_STATE marker=%s venue=%s activation=%s "
        "connected=%s ready=%s spendable=%s base_url=%s pem=%s",
        _MARKER,
        venue,
        os.environ.get(f"NIJA_{upper}_ACTIVATION_STATE", "unknown"),
        os.environ.get(f"NIJA_{upper}_CONNECTED", "0"),
        os.environ.get(f"NIJA_{upper}_TRADING_READY", "0"),
        os.environ.get(f"NIJA_{upper}_SPENDABLE_QUOTE", "unknown"),
        os.environ.get("OKX_BASE_URL", "default")
        if venue == "okx"
        else "api.coinbase.com",
        pem,
    )


def _install_activation_observer() -> None:
    try:
        import secondary_venue_activation_patch as patch
    except Exception as exc:
        logger.warning(
            "SECONDARY_VENUE_DIAGNOSTIC_IMPORT_PENDING marker=%s error=%s",
            _MARKER,
            type(exc).__name__,
        )
        return
    original = getattr(patch, "activate_once", None)
    if not callable(original) or getattr(
        original, "_nija_runtime_diag_v20260723", False
    ):
        return

    def wrapped(venue: Any, *args: Any, **kwargs: Any) -> str:
        name = str(getattr(venue, "name", "unknown"))
        try:
            result = original(venue, *args, **kwargs)
        except Exception:
            if name.lower() == "coinbase":
                _restore_coinbase_quarantine_state()
            _log_state(name, force=True)
            raise
        if name.lower() == "coinbase":
            _restore_coinbase_quarantine_state()
        _log_state(name, force=True)
        return result

    wrapped._nija_runtime_diag_v20260723 = True  # type: ignore[attr-defined]
    wrapped.__wrapped__ = original  # type: ignore[attr-defined]
    patch.activate_once = wrapped


def _install_scan_owner_repair() -> None:
    try:
        import reentrant_scan_owner_repair as repair

        repair.install()
    except Exception as exc:
        logger.warning(
            "REENTRANT_SCAN_OWNER_REPAIR_IMPORT_PENDING marker=%s error=%s",
            _MARKER,
            type(exc).__name__,
        )


def install() -> None:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
        _normalize_coinbase_env()
        try:
            import coinbase_authenticated_connect_recovery_patch as auth_recovery

            auth_recovery.install()
        except Exception:
            logger.exception(
                "COINBASE_AUTHENTICATED_CONNECT_RECOVERY_IMPORT_FAILED marker=%s",
                _MARKER,
            )
        try:
            import coinbase_capital_consistency_patch as consistency

            consistency.install()
        except Exception:
            logger.exception(
                "COINBASE_CAPITAL_CONSISTENCY_IMPORT_FAILED marker=%s",
                _MARKER,
            )
        _install_activation_observer()
        _install_scan_owner_repair()
        logger.warning(
            "SECONDARY_VENUE_RUNTIME_DIAGNOSTICS_INSTALLED marker=%s", _MARKER
        )


install()

__all__ = [
    "install",
    "normalize_coinbase_private_key",
    "_normalize_coinbase_env",
    "_quarantine_coinbase",
    "_restore_coinbase_quarantine_state",
]
