"""NIJA runtime release manifest and critical repair convergence audit."""
from __future__ import annotations

import importlib
import logging
import os
import re
import threading
import time
from typing import Callable

logger = logging.getLogger("nija.runtime_release_manifest")
RELEASE_ID = "20260817-runtime-convergence-v138"
# Immutable owner used by the v139 release-identity guard. Older convergence
# installers may register flags, but may not downgrade this manifest identity.
DECLARED_RELEASE_ID = RELEASE_ID
_INSTALLED = False
_LOCK = threading.RLock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

_INSTALLERS = (
    # Repair policy and module aliases before any identity/quiescence audit.
    ("bot.runtime_post_import_convergence_patch", "install"),
    ("runtime_module_identity_convergence_patch", "install_import_hook"),
    ("scan_wrapper_depth_convergence_patch", "install_import_hook"),
    ("scan_wrapper_convergence_repair_patch", "install"),
    ("bot.scan_reentrant_delegate_repair_patch", "install_import_hook"),
    ("broker_local_readiness_contract_patch", "install_import_hook"),
    ("bot.downstream_risk_governor_equity_repair_patch", "install_import_hook"),
    ("bot.secondary_credential_quarantine_patch", "install_import_hook"),
    ("runtime_convergence_hardening_patch", "install"),
    ("bot.production_runtime_convergence_v88_patch", "install_import_hook"),
    ("bot.kill_switch_coordinator_sync_patch", "install_import_hook"),
    ("bot.global_drawdown_capital_authority_v91_patch", "install_import_hook"),
    ("bot.zero_signal_streak_state_repair_patch", "install_import_hook"),
    ("bot.empty_position_sync_success_patch", "install_import_hook"),
    ("runtime_convergence_quiescence_patch", "install_import_hook"),
    ("bot.position_cost_basis_legacy_repair_patch", "install_import_hook"),
    ("bot.position_sync_runtime_repair_patch", "install_import_hook"),
    ("bot.kraken_equity_metadata_guard_patch", "install_import_hook"),
    ("bot.kraken_equity_runtime_patch", "install_import_hook"),
    ("bot.kraken_synthetic_equity_position_scrub_patch", "install_import_hook"),
    ("bot.kraken_equity_double_count_guard_patch", "install_import_hook"),
    ("bot.kraken_margin_auto_runtime_patch", "install_import_hook"),
    ("bot.kraken_all_account_exit_runtime_patch", "install_import_hook"),
    ("bot.kraken_exit_safety_convergence_patch", "install_import_hook"),
    ("bot.kraken_exit_final_guards_patch", "install_import_hook"),
    ("bot.kraken_exit_execution_safety_patch", "install_import_hook"),
    ("bot.kraken_exit_margin_cost_patch", "install_import_hook"),
    ("bot.kraken_exit_only_recovery_phase_guard_patch", "install_import_hook"),
    ("bot.kraken_profit_realization_guard_patch", "install_import_hook"),
    ("bot.coinbase_pem_quarantine_patch", "install_import_hook"),
    # v78 bounds synchronous balance-fetch waits inside the canonical 90-second
    # capital freshness contract. It is safe and idempotent, and does not extend
    # stale fallback age or broker timeouts.
    ("bot.capital_refresh_live_continuity_v78_patch", "install_import_hook"),
    # Must run after v133 and the activation/readiness modules it converges.
    # The installer is idempotent and reasserts ownership if older convergence
    # layers replay later in a long-running process.
    ("bot.readiness_proof_convergence_v134_patch", "install_import_hook"),
    # v135 prevents writer-only authority bootstrap under a protected stop and
    # makes publication expiry authoritative at read time. It also reasserts
    # the v78 dependency for long-running processes.
    ("bot.activation_stop_capital_freshness_v135_patch", "install_import_hook"),
    # v139 must run before v136: v136 historically wrote its own RELEASE_ID into
    # the parent manifest. The guard rewires that registration to be flag-only
    # and restores the canonical manifest identity before v136 is invoked.
    ("bot.runtime_release_identity_guard_patch", "install_import_hook"),
    # v136 makes the activation snapshot bridge observational only. Current
    # v134 proof plus the non-expired v135 publication are required before cycle
    # snapshot augmentation, and TradingStateMachine.commit_activation remains
    # the sole transition authority.
    ("bot.activation_publication_convergence_v136_patch", "install_import_hook"),
    # v137 schedules a canonical coordinator refresh before immutable capital
    # publication expiry, coalesces duplicate in-flight refreshes, and clamps
    # legacy-ready results when the publication proof is not current.
    ("bot.capital_publication_deadline_v137_patch", "install_import_hook"),
    # v138 makes the final execution/startup/router convergence probe idempotent,
    # targets StartupCoordinator.build_snapshot on the canonical class, and
    # terminates the 200 ms convergence watchdog once all three components are
    # already converged. No readiness, nonce, risk, or execution gate is relaxed.
    ("bot.final_execution_state_router_convergence_patch", "install_import_hook"),
)

_REQUIRED_FLAGS = {
    "post_import_convergence": "NIJA_RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED",
    "module_identity_guard": "NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED",
    "module_identity_ready": "NIJA_RUNTIME_MODULE_IDENTITY_READY",
    "convergence_quiescence_installed": "NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_INSTALLED",
    "convergence_quiescence_ready": "NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_READY",
    "scan_wrapper_depth_guard": "NIJA_SCAN_WRAPPER_DEPTH_GUARD_INSTALLED",
    "scan_wrapper_depth_ready": "NIJA_SCAN_WRAPPER_DEPTH_READY",
    "core_loop_limits": "NIJA_CORE_LOOP_PROGRESS_LIMITS_NORMALIZED",
    "production_runtime_convergence_v88": "NIJA_PRODUCTION_RUNTIME_CONVERGENCE_V88_INSTALLED",
    "kill_switch_coordinator_sync": "NIJA_KILL_SWITCH_COORDINATOR_SYNC_INSTALLED",
    "global_drawdown_aggregate_guard": "NIJA_GLOBAL_DRAWDOWN_AGGREGATE_GUARD_READY",
    "zero_signal_state_repair": "NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED",
    "zero_signal_state_ready": "NIJA_ZERO_SIGNAL_STREAK_STATE_READY",
    "empty_position_sync_patch": "NIJA_EMPTY_POSITION_SYNC_PATCH_INSTALLED",
    "empty_position_sync_ready": "NIJA_EMPTY_POSITION_SYNC_READY",
    "secondary_credential_quarantine": "NIJA_SECONDARY_CREDENTIAL_QUARANTINE_INSTALLED",
    "scan_reentrant_delegate_guard": "NIJA_SCAN_REENTRANT_DELEGATE_REPAIR_INSTALLED",
    "broker_local_readiness_contract": "NIJA_BROKER_LOCAL_READINESS_CONTRACT_INSTALLED",
    "downstream_risk_v2_installed": "NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED",
    "pre_dispatch_risk_fail_closed": "NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED",
    "pre_dispatch_risk_ready": "NIJA_PRE_DISPATCH_RISK_SIZING_READY",
    "kraken_equity_metadata_guard": "NIJA_KRAKEN_EQUITY_METADATA_GUARD_INSTALLED",
    "kraken_synthetic_equity_scrub": "NIJA_KRAKEN_SYNTHETIC_EQUITY_SCRUB_INSTALLED",
    "kraken_exit_only_recovery_guard": "NIJA_KRAKEN_EXIT_ONLY_RECOVERY_PHASE_GUARD_INSTALLED",
    "profit_realization_guard": "NIJA_KRAKEN_PROFIT_REALIZATION_GUARD_INSTALLED",
    "capital_refresh_live_continuity_v78": "NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED",
    "readiness_proof_convergence_v134": "NIJA_READINESS_PROOF_CONVERGENCE_V134_INSTALLED",
    "activation_stop_capital_freshness_v135": "NIJA_ACTIVATION_STOP_CAPITAL_FRESHNESS_V135_INSTALLED",
    "runtime_release_identity_v139": "NIJA_RUNTIME_RELEASE_IDENTITY_GUARD_INSTALLED",
    "activation_publication_convergence_v136": "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED",
    "capital_publication_deadline_v137": "NIJA_CAPITAL_PUBLICATION_DEADLINE_V137_INSTALLED",
    "final_execution_state_router_v138": "NIJA_FINAL_EXECUTION_STATE_ROUTER_READY",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _deployment_sha() -> str:
    for name in ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "SOURCE_VERSION", "RENDER_GIT_COMMIT", "HEROKU_SLUG_COMMIT"):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return "unknown"


def _invoke(module_name: str, function_name: str) -> tuple[bool, str]:
    try:
        module = importlib.import_module(module_name)
        installer: Callable = getattr(module, function_name)
        installer()
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def _expected_scan_wrapper_release() -> str:
    try:
        module = importlib.import_module("scan_wrapper_convergence_repair_patch")
        return str(getattr(module, "_MARKER", "") or "").strip()
    except Exception:
        return ""


def _scan_release_compatible(actual: str, expected: str) -> bool:
    actual = str(actual or "").strip()
    expected = str(expected or "").strip()
    return bool(actual and expected and actual == expected)


def _bounded_acyclic_scan(details: object) -> bool:
    text = str(details or "")
    match = re.search(r"depth=(\d+);max=(\d+);.*?cycle=(True|False|true|false)", text)
    if not match:
        return False
    depth = int(match.group(1))
    maximum = int(match.group(2))
    cycle = match.group(3).lower() == "true"
    return not cycle and depth <= maximum


def _readiness_contract_consistent() -> tuple[bool, str]:
    policy = str(os.environ.get("NIJA_SECONDARY_VENUE_POLICY", "") or "").strip().lower()
    missing = str(os.environ.get("NIJA_REQUIRED_VENUES_MISSING", "") or "").strip().strip(",")
    required_ready = _truthy(os.environ.get("NIJA_REQUIRED_VENUES_READY"))
    global_ready = _truthy(os.environ.get("NIJA_GLOBAL_TRADING_READY", os.environ.get("NIJA_MULTI_BROKER_TRADING_READY", "0")))
    active = str(os.environ.get("NIJA_ACTIVE_LIVE_VENUES", "") or "").strip().strip(",")
    if policy not in {"broker_local", "global_all_required", "optional"}:
        return False, f"invalid_policy:{policy or 'missing'}"
    if missing and required_ready:
        return False, f"contradiction:missing={missing};required_ready=1"
    if global_ready and not active:
        return False, "contradiction:global_ready=1;active_live_venues=missing"
    return True, f"policy={policy};required_ready={int(required_ready)};missing={missing or 'none'};global_ready={int(global_ready)};active={active or 'none'}"


def _runtime_limits_consistent() -> tuple[bool, str]:
    try:
        streak = int(float(os.environ.get("NIJA_ZERO_SIGNAL_STREAK_CAP", "999") or 999))
        stale = int(float(os.environ.get("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", "100") or 100))
        stall = float(os.environ.get("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S", "0") or 0)
    except Exception as exc:
        return False, f"parse_error:{exc}"
    ok = 2 <= streak <= 12 and stale > streak and stall >= 120.0
    return ok, f"zero_signal_streak_cap={streak};stale_threshold={stale};run_cycle_stall_warn_s={stall:.1f}"


def _audit() -> tuple[bool, dict[str, str]]:
    results: dict[str, str] = {}
    ready = True
    for module_name, function_name in _INSTALLERS:
        ok, reason = _invoke(module_name, function_name)
        results[module_name] = reason
        ready = ready and ok

    for module_name, key in (
        ("runtime_module_identity_convergence_patch", "module_identity_audit"),
        ("runtime_convergence_quiescence_patch", "convergence_quiescence_audit"),
        ("scan_wrapper_depth_convergence_patch", "scan_wrapper_depth_audit"),
    ):
        try:
            module = importlib.import_module(module_name)
            module_ready, module_details = module.audit()
            if module_name == "scan_wrapper_depth_convergence_patch" and not module_ready and _bounded_acyclic_scan(module_details):
                module_ready = True
                os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] = "1"
                results["scan_wrapper_depth_structural_accept"] = "bounded_acyclic=true"
            results[key] = str(module_details)
            ready = ready and bool(module_ready)
        except Exception as exc:
            results[key] = f"{type(exc).__name__}:{exc}"
            ready = False

    scan_release = str(os.environ.get("NIJA_SCAN_WRAPPER_RELEASE", "") or "").strip()
    expected_scan_release = _expected_scan_wrapper_release()
    if not _scan_release_compatible(scan_release, expected_scan_release):
        ready = False
        results["scan_wrapper_release"] = f"actual={scan_release or 'missing'};expected={expected_scan_release or 'missing'}"
    else:
        results["scan_wrapper_release"] = scan_release

    for label, flag in _REQUIRED_FLAGS.items():
        value = str(os.environ.get(flag, "") or "").strip()
        if value != "1":
            ready = False
            results[label] = value or "missing"
        else:
            results[label] = "ready"

    limits_ok, limits_reason = _runtime_limits_consistent()
    results["core_loop_runtime_limits"] = limits_reason
    ready = ready and limits_ok
    contract_ok, contract_reason = _readiness_contract_consistent()
    results["readiness_contract"] = contract_reason
    ready = ready and contract_ok
    return ready, results


def _publish(ready: bool, details: dict[str, str]) -> None:
    previous = os.environ.get("NIJA_RUNTIME_RELEASE_READY", "")
    # Re-anchor the mutable compatibility name before publishing. This is a
    # second line of defense if an older module was reloaded between audits.
    global RELEASE_ID
    RELEASE_ID = DECLARED_RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = DECLARED_RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_READY"] = "1" if ready else "0"
    logger.critical(
        "NIJA_RUNTIME_RELEASE_MANIFEST release=%s deployment_sha=%s ready=%s python_pid=%s details=%s",
        DECLARED_RELEASE_ID, _deployment_sha(), str(ready).lower(), os.getpid(), details,
    )
    if not ready:
        logger.critical(
            "RUNTIME_RELEASE_INCOMPLETE_EXECUTION_UNSAFE release=%s action=keep_broker_order_gates_fail_closed",
            DECLARED_RELEASE_ID,
        )
    elif previous == "0":
        logger.critical(
            "RUNTIME_RELEASE_CONVERGENCE_RECOVERED release=%s action=broker_order_gates_may_follow_normal_authority_checks",
            DECLARED_RELEASE_ID,
        )


def _watchdog() -> None:
    last_signature = ""
    while True:
        try:
            ready, details = _audit()
            signature = f"{ready}:{details}"
            if signature != last_signature:
                last_signature = signature
                _publish(ready, details)
        except Exception as exc:
            logger.critical("RUNTIME_RELEASE_AUDIT_FAILED release=%s error=%s", DECLARED_RELEASE_ID, exc)
        time.sleep(max(10.0, float(os.environ.get("NIJA_RUNTIME_RELEASE_AUDIT_INTERVAL_S", "30") or 30)))


def install_import_hook() -> None:
    global _INSTALLED
    with _LOCK:
        ready, details = _audit()
        _publish(ready, details)
        if not _INSTALLED:
            _INSTALLED = True
            threading.Thread(target=_watchdog, name="RuntimeReleaseManifest", daemon=True).start()
    logger.critical("NIJA_RUNTIME_RELEASE_MANIFEST_INSTALLED release=%s", DECLARED_RELEASE_ID)


__all__ = [
    "RELEASE_ID", "DECLARED_RELEASE_ID", "install_import_hook", "_audit", "_deployment_sha",
    "_expected_scan_wrapper_release", "_scan_release_compatible", "_bounded_acyclic_scan",
    "_readiness_contract_consistent", "_runtime_limits_consistent",
]
