"""Strict live startup sanitizer.

This module runs before the trading runtime imports authority/execution modules.
In every live mode, no local-writer, degraded-authority, or operator force-trade
flag may remain truthy. Redis being absent is a blocker, never permission to
replace distributed ownership with a process-local assertion.

The earliest startup path also installs the kill-switch provenance, failure
classification, durable guarded-replay, exchange rejection sample,
exchange-rejection provenance, dispatch provenance, Kraken capital admission,
stale rejection recovery, heartbeat recovery-liveness, and activation proof
truth repairs before normal runtime modules can instantiate or use the hard-stop
or activation singletons. These repairs never clear an unproven stop or grant
trading authority.

Production on 2026-08-27 first proved that merely listing dispatch provenance
among the early repairs was not sufficient: other repair imports could run
before v228 had patched the canonical execution telemetry boundary. V249 moved
v228 immediately behind v217.

A later clean-start observation proved one smaller ordering window remained.
The persisted global stop is already active during startup, and v224 is the
protector-boundary guard that rejects every synthetic ``exec-reject:pipeline:*``
result while that stop is active. Leaving v224 in the downstream repair list
allowed startup imports between v228 and v224 to append current-process samples
before the protector boundary was guarded. V250 therefore makes both v228 and
v224 mandatory provenance barriers immediately after v217. If either cannot
attach, no remaining early repair is imported and the runtime remains fail
closed.
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
_EARLY_SAFETY_REPAIRS_READY = False

# v217 must remain first because installing v228 imports ExecutionPipeline, whose
# import graph can touch kill-switch code. Immediately after v217, v228 protects
# the rejection-emission boundary and v224 protects the ExchangeKillSwitchProtector
# boundary for synthetic pipeline rejects while the persisted global stop is
# active. Both are hard prerequisites for every remaining early repair import.
_EARLY_KILL_SWITCH_PROVENANCE = (
    "kill_switch_early_provenance_v217_patch",
    "KILL_SWITCH_EARLY_V217",
)
_REQUIRED_REJECTION_PROVENANCE = (
    "exchange_reject_dispatch_provenance_v228_patch",
    "EXCHANGE_REJECT_DISPATCH_PROVENANCE_V228",
)
_REQUIRED_SYNTHETIC_STOP_PROVENANCE = (
    "exchange_reject_provenance_v224_patch",
    "EXCHANGE_REJECT_PROVENANCE_V224",
)
_REMAINING_EARLY_REPAIRS = (
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
        "runtime_kraken_capital_admission_v227_patch",
        "KRAKEN_CAPITAL_ADMISSION_V227",
    ),
    (
        "exchange_rejection_stale_latch_v226_patch",
        "EXCHANGE_REJECTION_STALE_LATCH_V226",
    ),
    (
        "runtime_heartbeat_killswitch_clear_wakeup_v225_patch",
        "HEARTBEAT_KILLSWITCH_CLEAR_WAKEUP_V225",
    ),
    (
        "runtime_activation_snapshot_proof_truth_v251_patch",
        "ACTIVATION_SNAPSHOT_PROOF_TRUTH_V251",
    ),
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


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _install_one_early_repair(module_name: str, label: str) -> bool:
    """Attach one early repair without mutating trading state on failure."""
    try:
        module = __import__(f"bot.{module_name}", fromlist=["install_import_hook"])
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        ok = callable(installer) and installer() is not False
        if not ok:
            logger.critical(
                "%s_EARLY_INSTALL_NOT_READY module=%s trading_fail_closed=true "
                "rejection_window_cleared=false kill_switch_unchanged=true "
                "execution_authority_unchanged=true forced_activation=false "
                "safety_gates_bypassed=false",
                label,
                module_name,
            )
        return bool(ok)
    except Exception as exc:
        logger.critical(
            "%s_EARLY_INSTALL_FAILED module=%s err=%s:%s trading_fail_closed=true "
            "rejection_window_cleared=false kill_switch_unchanged=true "
            "execution_authority_unchanged=true forced_activation=false "
            "safety_gates_bypassed=false",
            label,
            module_name,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False


def _install_early_safety_repairs() -> bool:
    """Install hard-stop root repairs before normal runtime imports.

    v217 is installed first so v228 can safely import/patch ExecutionPipeline
    without weakening kill-switch persistence provenance. v228 then protects the
    telemetry emission boundary, and v224 immediately protects the canonical
    ExchangeKillSwitchProtector boundary against synthetic pipeline rejects while
    a persisted global stop is active. No downstream early repair module is
    imported until all three protections are attached.

    Failure is deliberately fail-closed. This helper never clears a stop or a
    rejection window, marks execution ready, grants authority, or forces a trade.
    """
    global _EARLY_SAFETY_REPAIRS_ATTEMPTED, _EARLY_SAFETY_REPAIRS_READY
    if _EARLY_SAFETY_REPAIRS_ATTEMPTED:
        return _EARLY_SAFETY_REPAIRS_READY
    _EARLY_SAFETY_REPAIRS_ATTEMPTED = True
    _EARLY_SAFETY_REPAIRS_READY = False
    os.environ["NIJA_EARLY_SAFETY_REPAIRS_READY"] = "0"

    v217_module, v217_label = _EARLY_KILL_SWITCH_PROVENANCE
    if not _install_one_early_repair(v217_module, v217_label):
        logger.critical(
            "EARLY_SAFETY_REPAIR_CHAIN_BLOCKED marker=20260827-earliest-synthetic-rejection-boundary-v250 "
            "reason=kill_switch_early_provenance_unready downstream_imports_skipped=true "
            "dispatch_provenance_ready=false synthetic_stop_provenance_ready=false "
            "rejection_window_cleared=false kill_switch_unchanged=true "
            "execution_authority_unchanged=true forced_activation=false "
            "safety_gates_bypassed=false trading_fail_closed=true"
        )
        return False

    v228_module, v228_label = _REQUIRED_REJECTION_PROVENANCE
    if not _install_one_early_repair(v228_module, v228_label):
        logger.critical(
            "EARLY_SAFETY_REPAIR_CHAIN_BLOCKED marker=20260827-earliest-synthetic-rejection-boundary-v250 "
            "reason=exchange_reject_dispatch_provenance_unready downstream_imports_skipped=true "
            "dispatch_provenance_ready=false lifecycle_provenance_v247=false "
            "synthetic_stop_provenance_ready=false rejection_window_cleared=false "
            "kill_switch_unchanged=true execution_authority_unchanged=true "
            "forced_activation=false safety_gates_bypassed=false trading_fail_closed=true"
        )
        return False

    v224_module, v224_label = _REQUIRED_SYNTHETIC_STOP_PROVENANCE
    if not _install_one_early_repair(v224_module, v224_label):
        logger.critical(
            "EARLY_SAFETY_REPAIR_CHAIN_BLOCKED marker=20260827-earliest-synthetic-rejection-boundary-v250 "
            "reason=exchange_reject_synthetic_stop_provenance_unready downstream_imports_skipped=true "
            "dispatch_provenance_ready=true lifecycle_provenance_v247=true "
            "synthetic_stop_provenance_ready=false rejection_window_cleared=false "
            "kill_switch_unchanged=true execution_authority_unchanged=true "
            "forced_activation=false safety_gates_bypassed=false trading_fail_closed=true"
        )
        return False

    all_ready = True
    for module_name, label in _REMAINING_EARLY_REPAIRS:
        if not _install_one_early_repair(module_name, label):
            all_ready = False

    _EARLY_SAFETY_REPAIRS_READY = all_ready
    os.environ["NIJA_EARLY_SAFETY_REPAIRS_READY"] = "1" if all_ready else "0"
    logger.critical(
        "EARLIEST_SYNTHETIC_REJECTION_BOUNDARY_V250_READY "
        "marker=20260827-earliest-synthetic-rejection-boundary-v250 "
        "ready=%s kill_switch_provenance_v217=true dispatch_provenance_v228=true "
        "lifecycle_provenance_v247=true synthetic_stop_provenance_v224=true "
        "v224_before_downstream_repairs=true rejection_window_cleared=false "
        "kill_switch_unchanged=true execution_authority_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false trading_fail_closed=%s",
        str(all_ready).lower(),
        str(not all_ready).lower(),
    )
    return all_ready


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


def install_import_hook() -> bool:
    repairs_ready = _install_early_safety_repairs()
    sanitize("install_import_hook")
    return repairs_ready


# This must run before sanitize imports or the broader trading runtime can create
# the global KillSwitch singleton. v217 is intentionally first. v228 immediately
# follows, then v224 must protect the synthetic pipeline-reject boundary before
# v218/v221/v222/v225/v226/v227/v251 are imported. No startup path here clears a
# rejection sample or an active kill switch.
_install_early_safety_repairs()
sanitize("module_import")
