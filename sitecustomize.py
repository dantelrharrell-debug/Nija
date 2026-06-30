"""NIJA Python startup normalizer.

This module is imported automatically by Python. Keep it deterministic and
side-effect limited: normalize environment defaults before bot modules read them.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("nija.startup_patch")
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


def _clean(value: str | None) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text.strip().strip('"').strip("'").strip()


def _truthy_name(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _redis_configured() -> bool:
    return bool(
        _clean(os.environ.get("NIJA_REDIS_URL"))
        or _clean(os.environ.get("REDIS_URL"))
        or _clean(os.environ.get("REDIS_PRIVATE_URL"))
        or _clean(os.environ.get("REDIS_PUBLIC_URL"))
    )


def _live_mode() -> bool:
    return not _truthy_name("DRY_RUN_MODE") and not _truthy_name("PAPER_MODE")


def _env_name(*parts: str) -> str:
    return "_".join(parts)


def _force_strict_redis_authority(label: str = "startup") -> None:
    if not (_live_mode() and _redis_configured()):
        return
    cleared: list[str] = []
    tails = (
        ("UNSAFE", "BYPASS", "DISTRIBUTED", "LOCK"),
        ("DISABLE", "WRITER", "LOCK"),
        ("FORCE", "LOCAL", "WRITER", "LOCK", "FALLBACK"),
        ("ALLOW", "LOCAL", "WRITER", "LOCK", "FALLBACK"),
        ("ALLOW", "DEGRADED", "WRITER", "AUTHORITY"),
        ("ALLOW", "REDIS", "DEGRADED"),
        ("EMERGENCY", "LOCAL", "FALLBACK", "ACTIVE"),
        ("CONFIRM", "BYPASS", "RISKS"),
    )
    for tail in tails:
        key = _env_name("NIJA", *tail)
        if _truthy_name(key):
            os.environ[key] = "false"
            cleared.append(key)
    os.environ[_env_name("NIJA", "REQUIRE", "DISTRIBUTED", "LOCK")] = "true"
    os.environ[_env_name("NIJA", "STRICT", "REDIS", "LEASE")] = "1"
    os.environ[_env_name("NIJA", "STRICT", "WRITER", "LOCK")] = "true"
    os.environ[_env_name("NIJA", "FAIL", "CLOSED", "EXIT", "ON", "UNREACHABLE", "REDIS")] = "true"
    try:
        retries = int(float(os.environ.get(_env_name("NIJA", "FAIL", "CLOSED", "MAX", "RETRY", "ATTEMPTS"), "0") or "0"))
    except Exception:
        retries = 0
    if retries <= 0:
        os.environ[_env_name("NIJA", "FAIL", "CLOSED", "MAX", "RETRY", "ATTEMPTS")] = "12"
    if cleared:
        logger.warning("STRICT_REDIS_AUTHORITY_ENFORCED label=%s cleared=%s require_distributed_lock=true strict_redis_lease=1", label, ",".join(cleared))


def _normalize_okx() -> None:
    base = _clean(os.getenv("OKX_BASE_URL")).rstrip("/")
    if not base or base in {"https://www.okx.com", "https://openapi.okx.com"}:
        os.environ["OKX_BASE_URL"] = "https://us.okx.com"
    os.environ.setdefault("OKX_US_REGION", "true")
    for name in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE", "OKX_PASSPHRASE"):
        if name in os.environ:
            os.environ[name] = _clean(os.environ.get(name))


def _set_max_floor(name: str, value: float) -> None:
    current = _float_env(name, value)
    if name not in os.environ or current > value:
        os.environ[name] = str(value)


def _normalize_micro_cap_floors() -> None:
    if not _live_mode():
        return
    _set_max_floor("MIN_TRADE_USD", _float_env("NIJA_MICRO_CAP_MIN_TRADE_USD", 10.0))
    _set_max_floor("MIN_NOTIONAL_OVERRIDE", _float_env("NIJA_MICRO_CAP_MIN_NOTIONAL_USD", 10.0))
    _set_max_floor("MIN_CASH_TO_BUY", _float_env("NIJA_MICRO_CAP_MIN_CASH_TO_BUY_USD", 5.0))
    _set_max_floor("KRAKEN_MIN_NOTIONAL_USD", _float_env("NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD", 10.0))
    _set_max_floor("COINBASE_MIN_ORDER_USD", _float_env("NIJA_COINBASE_MICRO_MIN_ORDER_USD", 1.0))
    _set_max_floor("OKX_MIN_ORDER_USD", _float_env("NIJA_OKX_MICRO_MIN_ORDER_USD", 10.0))
    os.environ.setdefault("NIJA_MIN_NOTIONAL_SPENDABLE_CAP", "true")


def _runtime_defaults() -> None:
    defaults = {
        "NIJA_STARTUP_POSITION_SYNC_ENABLED": "true",
        "NIJA_BROKER_SCOPED_POSITION_CAP": "true",
        "NIJA_PROFITABILITY_GUARD_ENABLED": "true",
        "NIJA_LOG_TRADE_DECISIONS": "true",
        "NIJA_PENDING_ORDER_TIMEOUT_S": "90",
        "NIJA_RECONCILE_BROKER_OPEN_ORDERS": "true",
        "NIJA_COLLAPSE_STARTUP_REGISTRATION_GATE": "true",
        "NIJA_ADAPTIVE_MIN_NOTIONAL_ENABLED": "true",
        "NIJA_POST_LOCK_CAPITAL_REFRESH": "true",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


_force_strict_redis_authority("sitecustomize_import")
_normalize_okx()
_runtime_defaults()
_normalize_micro_cap_floors()
_force_strict_redis_authority("sitecustomize_final")
