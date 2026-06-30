"""Strict live startup sanitizer.

The logs showed a brief local-writer startup path before strict Redis authority
normalization corrected the environment. In live mode with Redis configured,
that path should never be visible. This module runs at package import and
normalizes the process environment before authority modules are imported.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("nija.strict_live_startup_sanitizer")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_FORBIDDEN_LIVE_FLAGS = (
    "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
    "NIJA_DISABLE_WRITER_LOCK",
    "NIJA_CONFIRM_BYPASS_RISKS",
    "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY",
    "NIJA_ALLOW_REDIS_DEGRADED",
    "NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE",
)


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
    try:
        attempts = int(float(os.environ.get("NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS", "0") or "0"))
    except Exception:
        attempts = 0
    if attempts <= 0:
        os.environ["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"] = "12"
    os.environ["NIJA_RUNTIME_DEGRADED_MODE"] = "false"
    if cleared:
        logger.warning("STRICT_LIVE_STARTUP_SANITIZED reason=%s cleared=%s", reason, ",".join(cleared))


def install_import_hook() -> None:
    sanitize("install_import_hook")


sanitize("module_import")
