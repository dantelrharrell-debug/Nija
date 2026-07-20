"""Normalize secondary-venue credentials and expose fail-closed diagnostics."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nija.secondary_venue_runtime_diagnostics")
_MARKER = "20260720-secondary-runtime-diagnostics-v3"
_INSTALLED = False
_LOCK = threading.RLock()
_LAST_LOG: dict[str, float] = {}


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def normalize_coinbase_private_key(value: str) -> str:
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
        if os.environ.get("NIJA_COINBASE_CONNECTED") == "1" and os.environ.get("NIJA_COINBASE_TRADING_READY") == "1":
            return True, "authenticated_connection"
        return False, f"{type(exc).__name__}:{str(exc)[:120]}"
    return True, "valid_es256"


def _normalize_coinbase_env() -> None:
    aliases = ("COINBASE_API_SECRET", "COINBASE_PLATFORM_API_SECRET", "COINBASE_ADVANCED_API_SECRET", "COINBASE_PEM_CONTENT")
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
        logger.warning("COINBASE_PEM_NORMALIZED marker=%s source=%s newline_count=%d reason=%s", _MARKER, source, normalized.count("\n"), reason)
    else:
        logger.error("COINBASE_PEM_INVALID marker=%s source=%s reason=%s", _MARKER, source, reason)


def _log_state(venue: str, *, force: bool = False) -> None:
    now = time.monotonic()
    if not force and now - _LAST_LOG.get(venue, 0.0) < 30.0:
        return
    _LAST_LOG[venue] = now
    upper = venue.upper()
    pem = os.environ.get("NIJA_COINBASE_PEM_STATE", "n/a") if venue == "coinbase" else "n/a"
    if venue == "coinbase" and os.environ.get("NIJA_COINBASE_CONNECTED") == "1" and os.environ.get("NIJA_COINBASE_TRADING_READY") == "1":
        pem = "valid"
        os.environ["NIJA_COINBASE_PEM_STATE"] = "valid"
    logger.warning(
        "SECONDARY_VENUE_RUNTIME_STATE marker=%s venue=%s activation=%s connected=%s ready=%s spendable=%s base_url=%s pem=%s",
        _MARKER, venue, os.environ.get(f"NIJA_{upper}_ACTIVATION_STATE", "unknown"),
        os.environ.get(f"NIJA_{upper}_CONNECTED", "0"), os.environ.get(f"NIJA_{upper}_TRADING_READY", "0"),
        os.environ.get(f"NIJA_{upper}_SPENDABLE_QUOTE", "unknown"),
        os.environ.get("OKX_BASE_URL", "default") if venue == "okx" else "api.coinbase.com", pem,
    )


def _install_activation_observer() -> None:
    try:
        import secondary_venue_activation_patch as patch
    except Exception as exc:
        logger.warning("SECONDARY_VENUE_DIAGNOSTIC_IMPORT_PENDING marker=%s error=%s", _MARKER, type(exc).__name__)
        return
    original = getattr(patch, "activate_once", None)
    if not callable(original) or getattr(original, "_nija_runtime_diag_v20260720", False):
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
    wrapped._nija_runtime_diag_v20260720 = True  # type: ignore[attr-defined]
    wrapped.__wrapped__ = original  # type: ignore[attr-defined]
    patch.activate_once = wrapped


def _install_scan_owner_repair() -> None:
    try:
        import reentrant_scan_owner_repair as repair
        repair.install()
    except Exception as exc:
        logger.warning("REENTRANT_SCAN_OWNER_REPAIR_IMPORT_PENDING marker=%s error=%s", _MARKER, type(exc).__name__)


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
            logger.exception("COINBASE_AUTHENTICATED_CONNECT_RECOVERY_IMPORT_FAILED marker=%s", _MARKER)
        try:
            import coinbase_capital_consistency_patch as consistency
            consistency.install()
        except Exception:
            logger.exception("COINBASE_CAPITAL_CONSISTENCY_IMPORT_FAILED marker=%s", _MARKER)
        _install_activation_observer()
        _install_scan_owner_repair()
        logger.warning("SECONDARY_VENUE_RUNTIME_DIAGNOSTICS_INSTALLED marker=%s", _MARKER)


install()

__all__ = ["install", "normalize_coinbase_private_key"]
