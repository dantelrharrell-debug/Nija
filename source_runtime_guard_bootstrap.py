"""Earliest source-level runtime guard bootstrap for NIJA."""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("nija.source_runtime_guard_bootstrap")
_MARKER = "20260715e"
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


def _set_status(value: str) -> None:
    for name in (
        "NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP",
        "NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_INSTALLED",
        "NIJA_SCAN_WRAPPER_DEPTH_GUARD_INSTALLED",
        "NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED",
        "NIJA_EMPTY_POSITION_SYNC_PATCH_INSTALLED",
        "NIJA_SECONDARY_CREDENTIAL_QUARANTINE_INSTALLED",
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
        "NIJA_DAILY_GAIN_PROFIT_HARVEST_INSTALLED",
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
            _install_required("scan_wrapper_depth_convergence_patch")
            _install_required("writer_generation_scope_repair_patch")
            _install_required("authority_heartbeat_generation_scope_patch")
            _install_required("final_worker_position_coinbase_repair_patch")
            _install_required("broker_auth_recovery_patch")
            _install_required("bot.secondary_credential_quarantine_patch")
            _install_required("runtime_convergence_hardening_patch")
            _install_required("bot.zero_signal_streak_state_repair_patch")
            _install_required("bot.empty_position_sync_success_patch")
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
            _install_required("bot.daily_gain_profit_harvest_patch")
            _install_required("three_venue_execution_readiness")
            _install_required("render_readiness_state_bridge")
            _install_required("scan_owner_okx_auth_convergence_patch")
            _install_required("runtime_convergence_quiescence_patch")

            identity = importlib.import_module("runtime_module_identity_convergence_patch")
            identity_ready, identity_details = identity.audit()
            if not identity_ready:
                raise RuntimeError(f"runtime_module_identity_incomplete:{identity_details}")

            quiescence = importlib.import_module("runtime_convergence_quiescence_patch")
            quiescence_ready, quiescence_details = quiescence.audit()
            if not quiescence_ready:
                raise RuntimeError(f"runtime_convergence_quiescence_incomplete:{quiescence_details}")

            scan_depth = importlib.import_module("scan_wrapper_depth_convergence_patch")
            scan_ready, scan_details = scan_depth.audit()
            if not scan_ready:
                raise RuntimeError(f"scan_wrapper_depth_incomplete:{scan_details}")

            _INSTALLED = True
            _set_status("1")
            message = (
                f"SOURCE_RUNTIME_GUARDS_READY marker={_MARKER} commit={_deployment_commit()} "
                "writer_authority=installed module_identity=verified convergence_quiescence=verified "
                "scan_wrapper_depth=verified zero_signal_state_repair=armed empty_position_sync=armed "
                "secondary_credential_quarantine=armed writer_generation_scope=installed "
                "authority_heartbeat_generation_scope=installed final_worker_position_coinbase_repair=installed "
                "broker_auth_recovery=installed runtime_convergence_hardening=installed runtime_convergence_v2=installed "
                "runtime_auth_endpoint_repair=installed final_runtime_convergence=installed scan_wrapper_convergence=installed "
                "venue_repair=installed secondary_venue_activation=installed secondary_venue_strict_readiness=installed "
                "broker_local_readiness_contract=installed account_exit_management_recovery=installed "
                "account_exit_recovery_bootstrap=installed daily_gain_profit_harvest=installed "
                "three_venue_stage_verifier=installed render_readiness_bridge=installed "
                "scan_owner_okx_auth_convergence=installed source=main_pre_bot"
            )
            logger.warning(message)
            print(f"[NIJA-PRINT] {message}", flush=True)
            return True
        except Exception as exc:
            _set_status("0")
            for name in (
                "NIJA_THREE_VENUE_EXECUTION_READY", "NIJA_RUNTIME_MODULE_IDENTITY_READY",
                "NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_READY", "NIJA_SCAN_WRAPPER_DEPTH_READY",
                "NIJA_ZERO_SIGNAL_STREAK_STATE_READY", "NIJA_EMPTY_POSITION_SYNC_READY",
                "NIJA_SECONDARY_CREDENTIAL_QUARANTINE_READY", "NIJA_DAILY_GAIN_PROFIT_HARVEST_INSTALLED",
            ):
                os.environ[name] = "0"
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


__all__ = ["install", "installed_marker"]
