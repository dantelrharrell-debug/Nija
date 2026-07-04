"""Strict live startup sanitizer.

This module runs before the trading runtime imports authority/execution modules.
In live mode with Redis configured, no local-writer, degraded-authority, or
operator force-trade flag may remain truthy. These flags previously allowed
startup code to re-open live execution gates after capital was already healthy.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("nija.strict_live_startup_sanitizer")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_FORBIDDEN_LIVE_FLAGS = (
    "FORCE_TRADE",
    "FORCE_TRADE_MODE",
    "FORCE_LIVE_TRANSITION",
    "NIJA_FORCE_ACTIVATION",
    "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
    "NIJA_DISABLE_WRITER_LOCK",
    "NIJA_CONFIRM_BYPASS_RISKS",
    "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY",
    "NIJA_ALLOW_REDIS_DEGRADED",
    "NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE",
)
_FALLBACK_SCORE_FLOOR_NORMALIZED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _redis_configured() -> bool:
    return bool(
        str(os.environ.get("NIJA_REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_URL", "")).strip()
        or str(os.environ.get("REDIS_PRIVATE_URL", "")).strip()
        or str(os.environ.get("REDIS_PUBLIC_URL", "")).strip()
    )


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _normalize_fallback_score_floor() -> None:
    """Keep dead-zone fallback tradable without weakening liquidity safety.

    The forced-fallback payload repair still performs hard geometry,
    positive-expectancy, and competitive-liquidity checks. This only prevents a
    stale fixed 60.0 score floor from vetoing otherwise selected micro-cap
    candidates during live dead-zone/Always-Trade cycles.
    """
    global _FALLBACK_SCORE_FLOOR_NORMALIZED
    floor_name = "NIJA_FALLBACK_STRICT_SCORE_FLOOR"
    target = _float_env("NIJA_FALLBACK_LIVE_ACTIVE_STRICT_SCORE_FLOOR", 40.0)
    target = max(35.0, min(target, 60.0))
    current = _float_env(floor_name, 60.0)
    if floor_name not in os.environ or current > target:
        os.environ[floor_name] = f"{target:.1f}"
        if not _FALLBACK_SCORE_FLOOR_NORMALIZED:
            _FALLBACK_SCORE_FLOOR_NORMALIZED = True
            logger.warning(
                "FALLBACK_STRICT_SCORE_FLOOR_NORMALIZED marker=20260704f floor=%.1f preserve_illiquid_policy=true preserve_positive_ev=true",
                target,
            )


def sanitize(reason: str = "package_import") -> None:
    if not (_live_mode() and _redis_configured()):
        return
    cleared: list[str] = []
    for key in _FORBIDDEN_LIVE_FLAGS:
        if _truthy(key):
            os.environ[key] = "false"
            cleared.append(key)
    os.environ["NIJA_REQUIRE_DISTRIBUTED_LOCK"] = "true"
    os.environ["NIJA_STRICT_REDIS_LEASE"] = "1"
    os.environ["NIJA_STRICT_WRITER_LOCK"] = "true"
    os.environ["NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS"] = "true"
    os.environ["NIJA_FAIL_CLOSED_RETRY_ON_LOCK_FAILURE"] = "true"
    try:
        attempts = int(float(os.environ.get("NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS", "0") or "0"))
    except Exception:
        attempts = 0
    if attempts <= 0:
        os.environ["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"] = "12"
    os.environ["NIJA_RUNTIME_DEGRADED_MODE"] = "false"
    _normalize_fallback_score_floor()
    if cleared:
        logger.warning("STRICT_LIVE_STARTUP_SANITIZED reason=%s cleared=%s", reason, ",".join(cleared))


def install_import_hook() -> None:
    sanitize("install_import_hook")


sanitize("module_import")
