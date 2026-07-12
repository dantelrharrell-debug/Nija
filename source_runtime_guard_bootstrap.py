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
_MARKER = "20260712b"
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
        "NIJA_BROKER_AUTH_RECOVERY_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_HARDENING_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_V2_INSTALLED",
        "NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED",
        "NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED",
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
            _install_required("broker_auth_recovery_patch")
            _install_required("runtime_convergence_hardening_patch")
            _install_required("runtime_convergence_v2_patch")
            _install_required("venue_readiness_execution_repair_patch")
            _install_required("secondary_venue_activation_patch")
            _install_required("secondary_venue_strict_readiness_patch")
            _install_required("account_exit_management_recovery_patch")
            _install_required("account_exit_recovery_bootstrap_patch")
            _install_required("three_venue_execution_readiness")
            _install_required("render_readiness_state_bridge")

            _INSTALLED = True
            _set_status("1")
            commit = _deployment_commit()
            message = (
                f"SOURCE_RUNTIME_GUARDS_READY marker={_MARKER} commit={commit} "
                "writer_authority=installed broker_auth_recovery=installed "
                "runtime_convergence_hardening=installed runtime_convergence_v2=installed "
                "venue_repair=installed secondary_venue_activation=installed "
                "secondary_venue_strict_readiness=installed account_exit_management_recovery=installed "
                "account_exit_recovery_bootstrap=installed three_venue_stage_verifier=installed "
                "render_readiness_bridge=installed source=main_pre_bot"
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
