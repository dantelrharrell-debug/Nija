"""Strict live startup sanitizer.

This module runs before the trading runtime imports authority/execution modules.
In every live mode, no local-writer, degraded-authority, or operator force-trade
flag may remain truthy. Redis being absent is a blocker, never permission to
replace distributed ownership with a process-local assertion.

The earliest startup path also installs the kill-switch provenance, failure
classification, durable guarded-replay, exchange rejection sample,
exchange-rejection provenance, and heartbeat recovery-liveness repairs before
normal runtime modules can instantiate or use the hard-stop singleton. These
repairs never clear an unproven stop or grant trading authority.
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
_EARLY_SAFETY_REPAIRS_ATTEMPTED = False


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


def _install_early_safety_repairs() -> None:
    """Install hard-stop root repairs before normal runtime imports.

    Failure is deliberately fail-closed: this helper never clears a stop, marks a
    readiness bit, or grants execution authority. It only installs code repairs
    and emits a critical diagnostic if one cannot attach.
    """
    global _EARLY_SAFETY_REPAIRS_ATTEMPTED
    if _EARLY_SAFETY_REPAIRS_ATTEMPTED:
        return
    _EARLY_SAFETY_REPAIRS_ATTEMPTED = True

    repairs = (
        (
            "kill_switch_early_provenance_v217_patch",
            "KILL_SWITCH_EARLY_V217",
        ),
        (
            "failure_mode_auth_classification_v218_patch",
            "FAILURE_MODE_AUTH_V218",
        ),
        (
            "kill_switch_durable_replay_v221_patch",
            "KILL_SWITCH_DURABLE_REPLAY_V221",
        ),
        (
            "exchange_rejection_sample_guard_v222_patch",
            "EXCHANGE_REJECTION_SAMPLE_GUARD_V222",
        ),
        (
            "exchange_reject_provenance_v224_patch",
            "EXCHANGE_REJECT_PROVENANCE_V224",
        ),
        (
            "runtime_heartbeat_killswitch_clear_wakeup_v225_patch",
            "HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225",
        ),
    )
    for module_name, label in repairs:
        try:
            module = __import__(f"bot.{module_name}", fromlist=["install_import_hook"])
            installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
            ok = callable(installer) and installer() is not False
            if not ok:
                logger.critical(
                    "%s_EARLY_INSTALL_NOT_READY module=%s trading_fail_closed=true "
                    "execution_authority_unchanged=true",
                    label,
                    module_name,
                )
        except Exception as exc:
            logger.critical(
                "%s_EARLY_INSTALL_FAILED module=%s err=%s:%s trading_fail_closed=true "
                "execution_authority_unchanged=true",
                label,
                module_name,
                type(exc).__name__,
                exc,
                exc_info=True,
            )


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
    if not _live_mode():
        return
    cleared: list[str] = []
    for key in _FORBIDDEN_LIVE_FLAGS:
        if _truthy(key):
            os.environ[key] = "false"
            cleared.append(key)
    os.environ["NIJA_REQUIRE_DISTRIBUTED_LOCK"] = "true"
    os.environ["NIJA_ECEL_REQUIRED"] = "true"
    os.environ["NIJA_ECEL_FAIL_CLOSED"] = "true"
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
    os.environ["NIJA_REDIS_CONFIGURED"] = "1" if _redis_configured() else "0"
    _normalize_fallback_score_floor()
    if cleared:
        logger.warning("STRICT_LIVE_STARTUP_SANITIZED reason=%s cleared=%s", reason, ",".join(cleared))


def install_import_hook() -> None:
    _install_early_safety_repairs()
    sanitize("install_import_hook")


# This must run before sanitize imports or the broader trading runtime can create
# the global KillSwitch singleton. Importing bot.kill_switch defines the class but
# does not instantiate the singleton, so v217 can safely patch constructor-time
# file handling before the first get_kill_switch() call. v221/v222/v224/v225 do
# not force release-manifest imports here; they wait for canonical runtime loading.
_install_early_safety_repairs()
sanitize("module_import")
