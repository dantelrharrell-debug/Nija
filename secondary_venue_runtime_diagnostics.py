"""Normalize secondary-venue credentials and expose fail-closed diagnostics.

This module is safe to import during Python site initialization. It never logs
credential values, never marks a venue connected, and never bypasses exchange,
risk, funding, or execution checks.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nija.secondary_venue_runtime_diagnostics")
_MARKER = "20260713b"
_INSTALLED = False
_LOCK = threading.RLock()
_LAST_LOG: dict[str, float] = {}


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def normalize_coinbase_private_key(value: str) -> str:
    """Return a PEM string suitable for Coinbase's Python SDK.

    Render and other dashboards commonly store multiline values with literal
    ``\\n`` sequences. Coinbase requires those newlines to be restored.
    """
    value = _strip_outer_quotes(str(value or ""))
    value = value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    value = value.strip()
    return value + ("\n" if value else "")


def _validate_coinbase_key(secret: str) -> tuple[bool, str]:
    if not secret:
        return False, "missing"
    if "-----BEGIN" not in secret or "PRIVATE KEY-----" not in secret:
        return False, "missing_pem_header"
    try:
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(secret.encode("utf-8"), password=None)
        curve = getattr(getattr(key, "curve", None), "name", "unknown")
        if curve not in {"secp256r1", "prime256v1"}:
            return False, f"unsupported_curve:{curve}"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{str(exc)[:120]}"
    return True, "valid_es256"


def _normalize_coinbase_env() -> None:
    aliases = ("COINBASE_API_SECRET", "COINBASE_PLATFORM_API_SECRET", "COINBASE_ADVANCED_API_SECRET")
    source = next((name for name in aliases if os.environ.get(name, "").strip()), "")
    if not source:
        os.environ["NIJA_COINBASE_PEM_STATE"] = "missing"
        logger.error("COINBASE_PEM_INVALID marker=%s reason=missing_secret", _MARKER)
        return

    normalized = normalize_coinbase_private_key(os.environ[source])
    for name in aliases:
        if name == source or not os.environ.get(name, "").strip():
            os.environ[name] = normalized

    valid, reason = _validate_coinbase_key(normalized)
    os.environ["NIJA_COINBASE_PEM_STATE"] = "valid" if valid else "invalid"
    if valid:
        logger.warning(
            "COINBASE_PEM_NORMALIZED marker=%s source=%s newline_count=%d format=ES256",
            _MARKER,
            source,
            normalized.count("\n"),
        )
    else:
        logger.error(
            "COINBASE_PEM_INVALID marker=%s source=%s reason=%s action=replace_with_cdp_ecdsa_private_key",
            _MARKER,
            source,
            reason,
        )


def _log_state(venue: str, *, force: bool = False) -> None:
    now = time.monotonic()
    if not force and now - _LAST_LOG.get(venue, 0.0) < 30.0:
        return
    _LAST_LOG[venue] = now
    upper = venue.upper()
    logger.warning(
        "SECONDARY_VENUE_RUNTIME_STATE marker=%s venue=%s activation=%s connected=%s ready=%s spendable=%s base_url=%s pem=%s",
        _MARKER,
        venue,
        os.environ.get(f"NIJA_{upper}_ACTIVATION_STATE", "unknown"),
        os.environ.get(f"NIJA_{upper}_CONNECTED", "0"),
        os.environ.get(f"NIJA_{upper}_TRADING_READY", "0"),
        os.environ.get(f"NIJA_{upper}_SPENDABLE_QUOTE", "unknown"),
        os.environ.get("OKX_BASE_URL", "default") if venue == "okx" else "api.coinbase.com",
        os.environ.get("NIJA_COINBASE_PEM_STATE", "n/a") if venue == "coinbase" else "n/a",
    )


def _install_activation_observer() -> None:
    try:
        import secondary_venue_activation_patch as patch
    except Exception as exc:
        logger.warning("SECONDARY_VENUE_DIAGNOSTIC_IMPORT_PENDING marker=%s error=%s", _MARKER, type(exc).__name__)
        return

    original = getattr(patch, "activate_once", None)
    if not callable(original) or getattr(original, "_nija_runtime_diag_v20260713b", False):
        return

    def wrapped(venue: Any, *args: Any, **kwargs: Any) -> str:
        name = str(getattr(venue, "name", "unknown"))
        try:
            result = original(venue, *args, **kwargs)
        except Exception:
            _log_state(name, force=True)
            raise
        _log_state(name, force=True)
        return result

    wrapped._nija_runtime_diag_v20260713b = True  # type: ignore[attr-defined]
    wrapped.__wrapped__ = original  # type: ignore[attr-defined]
    patch.activate_once = wrapped


def install() -> None:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
        _normalize_coinbase_env()
        _install_activation_observer()
        logger.warning("SECONDARY_VENUE_RUNTIME_DIAGNOSTICS_INSTALLED marker=%s", _MARKER)


install()

__all__ = ["install", "normalize_coinbase_private_key"]
