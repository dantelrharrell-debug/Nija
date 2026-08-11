"""Live Redis execution-bypass guard.

Live mode must never inherit local-writer fallback or force-trade flags. The
execution sources enforce their own gates directly; this module only performs
deterministic environment normalization and deliberately does not monkeypatch
imports or execution methods.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("nija.live_redis_execution_bypass_guard")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


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


def _env_name(*parts: str) -> str:
    return "_".join(parts)


def sanitize(label: str) -> None:
    if not _live_mode():
        return
    cleared = []
    for key in (
        "FORCE_TRADE",
        "FORCE_TRADE_MODE",
        "FORCE_LIVE_TRANSITION",
        "FORCE_SYSTEM_READY",
        "NIJA_FORCE_ACTIVATION",
        "NIJA_FORCE_KRAKEN_ONLY_TEST",
        "NIJA_KRAKEN_TEST_LIFT_CAPITAL_GATES",
        "NIJA_PLATFORM_LIFT_CAPITAL_GATES",
        "COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR",
        "NIJA_CAPITAL_OPPORTUNISTIC",
        "FORCE_FIRST_TRADE",
        "FORCE_TRADE_ON_FIRST_VALID_SIGNAL",
        "ALLOW_SMALL_ORDERS",
        "ALLOW_SMALL_ACCOUNT_TRADING",
        "NIJA_AUTO_CLEAR_EMERGENCY_STOP",
        "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
        "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK",
        "NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY",
        "NIJA_ALLOW_REDIS_DEGRADED",
        "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
        "NIJA_DISABLE_WRITER_LOCK",
        "NIJA_CONFIRM_BYPASS_RISKS",
    ):
        if _truthy(key):
            os.environ[key] = "false"
            cleared.append(key)
    os.environ[_env_name("NIJA", "REQUIRE", "DISTRIBUTED", "LOCK")] = "true"
    os.environ["NIJA_ECEL_REQUIRED"] = "true"
    os.environ["NIJA_ECEL_FAIL_CLOSED"] = "true"
    os.environ[_env_name("NIJA", "STRICT", "REDIS", "LEASE")] = "1"
    os.environ[_env_name("NIJA", "STRICT", "WRITER", "LOCK")] = "true"
    os.environ[_env_name("NIJA", "RUNTIME", "DEGRADED", "MODE")] = "false"
    os.environ["NIJA_REDIS_CONFIGURED"] = "1" if _redis_configured() else "0"
    if cleared:
        logger.critical("LIVE_REDIS_EXECUTION_BYPASS_GUARD label=%s cleared=%s", label, ",".join(cleared))


def install_import_hook() -> None:
    sanitize("install")
    logger.warning(
        "LIVE_REDIS_EXECUTION_BYPASS_GUARD_INSTALL_COMPLETE "
        "mode=environment_normalization runtime_monkeypatch=false"
    )
