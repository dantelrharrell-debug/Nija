"""Earliest source-level runtime guard bootstrap for NIJA.

This module is loaded before the first ``bot.*`` import. It acquires canonical
writer lineage and installs mandatory authentication, broker-isolation, account
recovery, worker-deduplication and readiness guards. Live-capital startup fails
closed if a required guard cannot be installed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("nija.source_runtime_guard_bootstrap")
_MARKER = "20260715a"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUTHY


def _is_live_runtime() -> bool:
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False
    return any(_truthy(name) for name in (
        "LIVE_CAPITAL_VERIFIED", "NIJA_EXECUTION_ACTIVE", "NIJA_RUNTIME_EXECUTION_AUTHORITY",
    ))


def _deployment_commit() -> str:
    for name in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "RAILWAY_GIT_COMMIT_SHA", "COMMIT_SHA", "SOURCE_VERSION"):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return "unknown"


def _install_required(module_name: str) -> None:
    module = importlib.import_module(module_name)
    installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
    if not callable(installer):
        raise RuntimeError(f"{module_name} installer is missing")
    installer()


def _critical_identity_invariants(details: dict[str, str]) -> tuple[bool, str]:
    """Validate only conditions that can make live execution unsafe.

    Initial sitecustomize recovery is expected and may leave a stale advisory
    duplicate latch from an earlier audit pass. The latch may be cleared only when
    the current audit proves the required risk module is canonical, the execution
    chain contains v2 and no legacy/cycle layer, both Phase 3 streak guards are
    attached without a cycle, and no recovered module reports duplicate=true.
    """
    risk = str(details.get("downstream_risk_module", ""))
    pipeline = str(details.get("execution_pipeline_chain", ""))
    streak = str(details.get("zero_signal_streak_chain", ""))
    duplicate_values = [
        f"{key}={value}"
        for key, value in details.items()
        if "duplicate=true" in str(value).lower()
    ]
    checks = {
        "risk_identity": "same=True" in risk and "marker=20260714-downstream-risk-v2" in risk,
        "pipeline_v2": "v2=True" in pipeline,
        "pipeline_no_legacy": "legacy=False" in pipeline,
        "pipeline_no_cycle": "cycle=False" in pipeline,
        "streak_cap": "cap_guard=True" in streak,
        "streak_state": "state_repair=True" in streak,
        "streak_no_cycle": "cycle=False" in streak,
        "no_reported_duplicates": not duplicate_values,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return not failed, ";".join(failed or ["all_critical_invariants_ready"])


def _set_status(value: str) -> None:
    for name in (
        "NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP",
        "NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED",
        "NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED",
        "NIJA_BROKER_AUTH_RECOVERY_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_HARDENING_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_V2_INSTALLED",
        "NIJA_RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED",
        "NIJA_FINAL_RUNTIME_CONVERGENCE_INSTALLED",
        "NIJA_SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED",
        "NIJA_SCAN_OWNER_OKX_AUTH_CONVERGENCE_INSTALLED",
        "NIJA_WRITER_GENERATION_SCOPE_REPAIR_INSTALLED",
        "NIJA_AUTHORITY_HEARTBEAT_GENERATION_SCOPE_INSTALLED",
        "NIJA_FINAL_WORKER_POSITION_COINBASE_REPAIR_INSTALLED",
        "NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED",
        "NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED",
        "NIJA_BROKER_LOCAL_READINESS_CONTRACT_INSTALLED",
        "NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALLED",
        "NIJA_ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_INSTALLED",
        "NIJA_THREE_VENUE_STAGE_VERIFIER_INSTALLED",
        "NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED",
        "NIJA_RENDER_READINESS_BRIDGE_INSTALLED",
    ):
        os.environ[name] = value
    os.environ["NIJA_VENUE_READINESS_SOURCE_MARKER"] = _MARKER


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        try:
            _install_required("prebot_writer_authority_fail_closed")
            _install_required("runtime_module_identity_convergence_patch")
            _install_required("writer_generation_scope_repair_patch")
            _install_required("authority_heartbeat_generation_scope_patch")
            _install_required("final_worker_position_coinbase_repair_patch")
            _install_required("broker_auth_recovery_patch")
            _install_required("runtime_convergence_hardening_patch")
            _install_required("bot.zero_signal_streak_state_repair_patch")
            _install_required("runtime_convergence_v2_patch")
            _install_required("runtime_auth_recursion_endpoint_repair_patch")
            _install_required("final_runtime_convergence_patch")
            _install_required("scan_wrapper_convergence_repair_patch")
            _install_required("venue_readiness_execution_repair_patch")
            _install_required("secondary_venue_activation_patch")
            _install_required("secondary_venue_strict_readiness_patch")
            _install_required("broker_local_readiness_contract_patch")
            _install_required("account_exit_management_recovery_patch")
            _install_required("account_exit_recovery_bootstrap_patch")
            _install_required("three_venue_execution_readiness")
            _install_required("render_readiness_state_bridge")
            _install_required("scan_owner_okx_auth_convergence_patch")

            identity = importlib.import_module("runtime_module_identity_convergence_patch")
            audit = getattr(identity, "audit", None)
            if callable(audit):
                ready, details = audit()
                if not ready:
                    critical_ready, reason = _critical_identity_invariants(details)
                    if not critical_ready:
                        raise RuntimeError(
                            f"runtime_module_identity_critical_failure:{reason}:{details}"
                        )
                    # The current state is proven canonical and safe. Clear only the
                    # stale advisory latch, then require a clean second audit.
                    previous = os.environ.get("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", "")
                    os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] = "0"
                    ready, second_details = audit()
                    if not ready:
                        os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] = previous
                        raise RuntimeError(
                            f"runtime_module_identity_recheck_failed:{second_details}"
                        )
                    os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] = "1"
                    logger.warning(
                        "RUNTIME_MODULE_IDENTITY_STALE_LATCH_CLEARED marker=%s previous=%s reason=%s",
                        _MARKER,
                        previous or "unset",
                        reason,
                    )

            _INSTALLED = True
            _set_status("1")
            commit = _deployment_commit()
            message = (
                f"SOURCE_RUNTIME_GUARDS_READY marker={_MARKER} commit={commit} "
                "writer_authority=installed module_identity=verified zero_signal_state_repair=armed "
                "writer_generation_scope=installed authority_heartbeat_generation_scope=installed "
                "final_worker_position_coinbase_repair=installed broker_auth_recovery=installed "
                "runtime_convergence_hardening=installed runtime_convergence_v2=installed "
                "runtime_auth_endpoint_repair=installed final_runtime_convergence=installed "
                "scan_wrapper_convergence=installed venue_repair=installed "
                "secondary_venue_activation=installed secondary_venue_strict_readiness=installed "
                "broker_local_readiness_contract=installed "
                "account_exit_management_recovery=installed account_exit_recovery_bootstrap=installed "
                "three_venue_stage_verifier=installed render_readiness_bridge=installed "
                "scan_owner_okx_auth_convergence=installed source=main_pre_bot"
            )
            logger.warning(message)
            print(f"[NIJA-PRINT] {message}", flush=True)
            return True
        except Exception as exc:
            _set_status("0")
            os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] = "0"
            os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] = "0"
            os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "0"
            message = f"{type(exc).__name__}:{exc}"
            live = _is_live_runtime()
            logger.critical(
                "SOURCE_RUNTIME_GUARDS_FAILED marker=%s commit=%s error=%s live=%s",
                _MARKER, _deployment_commit(), message, live, exc_info=True,
            )
            print(
                f"[NIJA-PRINT] SOURCE_RUNTIME_GUARDS_FAILED marker={_MARKER} "
                f"commit={_deployment_commit()} error={message[:240]} live={str(live).lower()}",
                flush=True,
            )
            if live:
                raise SystemExit(78) from exc
            return False


def installed_marker() -> Optional[str]:
    return _MARKER if _INSTALLED else None


__all__ = ["install", "installed_marker", "_critical_identity_invariants"]
