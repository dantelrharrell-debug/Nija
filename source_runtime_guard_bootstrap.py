"""Earliest source-level runtime guard bootstrap for NIJA.

The bootstrap installs safety guards in a deterministic order. Legacy
convergence watchdogs are deliberately disabled; they repeatedly rewrote live
scan methods and caused the wrapper storm seen in production.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("nija.source_runtime_guard_bootstrap")
_MARKER = "20260713f"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUTHY


def _is_live_runtime() -> bool:
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False
    return any(_truthy(name) for name in (
        "LIVE_CAPITAL_VERIFIED",
        "NIJA_EXECUTION_ACTIVE",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
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
    result = installer()
    if result is False:
        raise RuntimeError(f"{module_name} installer reported failure")


def _set_status(value: str) -> None:
    active = (
        "NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP",
        "NIJA_BROKER_AUTH_RECOVERY_INSTALLED",
        "NIJA_RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED",
        "NIJA_FINAL_RUNTIME_CONVERGENCE_INSTALLED",
        "NIJA_SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED",
        "NIJA_SCAN_OWNER_OKX_AUTH_CONVERGENCE_INSTALLED",
        "NIJA_WRITER_GENERATION_SCOPE_REPAIR_INSTALLED",
        "NIJA_AUTHORITY_HEARTBEAT_GENERATION_SCOPE_INSTALLED",
        "NIJA_FINAL_WORKER_POSITION_COINBASE_REPAIR_INSTALLED",
        "NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED",
        "NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED",
        "NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALLED",
        "NIJA_ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_INSTALLED",
        "NIJA_THREE_VENUE_STAGE_VERIFIER_INSTALLED",
        "NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED",
        "NIJA_RENDER_READINESS_BRIDGE_INSTALLED",
    )
    for name in active:
        os.environ[name] = value
    os.environ["NIJA_RUNTIME_CONVERGENCE_HARDENING_INSTALLED"] = "0"
    os.environ["NIJA_RUNTIME_CONVERGENCE_V2_INSTALLED"] = "0"
    os.environ["NIJA_RUNTIME_CONVERGENCE_WATCHDOGS_DISABLED"] = "1"
    os.environ["NIJA_VENUE_READINESS_SOURCE_MARKER"] = _MARKER


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        try:
            _install_required("prebot_writer_authority_fail_closed")
            _install_required("writer_generation_scope_repair_patch")
            _install_required("authority_heartbeat_generation_scope_patch")
            _install_required("final_worker_position_coinbase_repair_patch")
            _install_required("broker_auth_recovery_patch")
            _install_required("runtime_auth_recursion_endpoint_repair_patch")
            _install_required("final_runtime_convergence_patch")
            _install_required("venue_readiness_execution_repair_patch")
            _install_required("secondary_venue_activation_patch")
            _install_required("secondary_venue_strict_readiness_patch")
            _install_required("account_exit_management_recovery_patch")
            _install_required("account_exit_recovery_bootstrap_patch")
            _install_required("three_venue_execution_readiness")
            _install_required("render_readiness_state_bridge")
            _install_required("scan_wrapper_convergence_repair_patch")
            _install_required("scan_owner_okx_auth_convergence_patch")

            _INSTALLED = True
            _set_status("1")
            commit = _deployment_commit()
            message = (
                f"SOURCE_RUNTIME_GUARDS_READY marker={_MARKER} commit={commit} "
                "writer_authority=installed writer_generation_scope=installed "
                "authority_heartbeat_generation_scope=installed "
                "broker_auth_recovery=installed runtime_auth_endpoint_repair=installed "
                "final_runtime_convergence=one_shot scan_wrapper_convergence=canonical_one_shot "
                "scan_owner_okx_auth_convergence=broker_only_one_shot "
                "legacy_convergence_watchdogs=disabled source=main_pre_bot"
            )
            logger.warning(message)
            print(f"[NIJA-PRINT] {message}", flush=True)
            return True
        except Exception as exc:
            _set_status("0")
            os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] = "0"
            message = f"{type(exc).__name__}:{exc}"
            live = _is_live_runtime()
            logger.critical(
                "SOURCE_RUNTIME_GUARDS_FAILED marker=%s commit=%s error=%s live=%s",
                _MARKER,
                _deployment_commit(),
                message,
                live,
                exc_info=True,
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
