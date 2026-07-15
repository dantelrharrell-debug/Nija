"""NIJA runtime release manifest and critical repair convergence audit."""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Callable

logger = logging.getLogger("nija.runtime_release_manifest")
RELEASE_ID = "20260715-runtime-convergence-v12"
_INSTALLED = False
_LOCK = threading.RLock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

_INSTALLERS = (
    ("runtime_module_identity_convergence_patch", "install_import_hook"),
    ("scan_wrapper_depth_convergence_patch", "install_import_hook"),
    ("scan_wrapper_convergence_repair_patch", "install"),
    ("bot.scan_reentrant_delegate_repair_patch", "install_import_hook"),
    ("broker_local_readiness_contract_patch", "install_import_hook"),
    ("bot.downstream_risk_governor_equity_repair_patch", "install_import_hook"),
    ("runtime_convergence_hardening_patch", "install"),
    ("bot.zero_signal_streak_state_repair_patch", "install_import_hook"),
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
)

_REQUIRED_FLAGS = {
    "module_identity_guard": "NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED",
    "module_identity_ready": "NIJA_RUNTIME_MODULE_IDENTITY_READY",
    "convergence_quiescence_installed": "NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_INSTALLED",
    "convergence_quiescence_ready": "NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_READY",
    "scan_wrapper_depth_guard": "NIJA_SCAN_WRAPPER_DEPTH_GUARD_INSTALLED",
    "scan_wrapper_depth_ready": "NIJA_SCAN_WRAPPER_DEPTH_READY",
    "core_loop_limits": "NIJA_CORE_LOOP_PROGRESS_LIMITS_NORMALIZED",
    "zero_signal_state_repair": "NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED",
    "zero_signal_state_ready": "NIJA_ZERO_SIGNAL_STREAK_STATE_READY",
    "scan_reentrant_delegate_guard": "NIJA_SCAN_REENTRANT_DELEGATE_REPAIR_INSTALLED",
    "broker_local_readiness_contract": "NIJA_BROKER_LOCAL_READINESS_CONTRACT_INSTALLED",
    "downstream_risk_v2_installed": "NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED",
    "pre_dispatch_risk_fail_closed": "NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED",
    "pre_dispatch_risk_ready": "NIJA_PRE_DISPATCH_RISK_SIZING_READY",
    "kraken_equity_metadata_guard": "NIJA_KRAKEN_EQUITY_METADATA_GUARD_INSTALLED",
    "kraken_synthetic_equity_scrub": "NIJA_KRAKEN_SYNTHETIC_EQUITY_SCRUB_INSTALLED",
    "kraken_exit_only_recovery_guard": "NIJA_KRAKEN_EXIT_ONLY_RECOVERY_PHASE_GUARD_INSTALLED",
    "profit_realization_guard": "NIJA_KRAKEN_PROFIT_REALIZATION_GUARD_INSTALLED",
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
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_READY"] = "1" if ready else "0"
    logger.critical("NIJA_RUNTIME_RELEASE_MANIFEST release=%s deployment_sha=%s ready=%s python_pid=%s details=%s", RELEASE_ID, _deployment_sha(), str(ready).lower(), os.getpid(), details)
    if not ready:
        logger.critical("RUNTIME_RELEASE_INCOMPLETE_EXECUTION_UNSAFE release=%s action=keep_broker_order_gates_fail_closed", RELEASE_ID)


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
            logger.critical("RUNTIME_RELEASE_AUDIT_FAILED release=%s error=%s", RELEASE_ID, exc)
        time.sleep(max(30.0, float(os.environ.get("NIJA_RUNTIME_RELEASE_AUDIT_INTERVAL_S", "120") or 120)))


def install_import_hook() -> None:
    global _INSTALLED
    with _LOCK:
        ready, details = _audit()
        _publish(ready, details)
        if not _INSTALLED:
            _INSTALLED = True
            threading.Thread(target=_watchdog, name="RuntimeReleaseManifest", daemon=True).start()
    logger.critical("NIJA_RUNTIME_RELEASE_MANIFEST_INSTALLED release=%s", RELEASE_ID)


__all__ = ["RELEASE_ID", "install_import_hook", "_audit", "_deployment_sha", "_expected_scan_wrapper_release", "_scan_release_compatible", "_readiness_contract_consistent", "_runtime_limits_consistent"]
