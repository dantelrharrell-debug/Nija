"""Repair v130 kill-switch recovery causality and v58/v61 readiness precedence.

v131 is deliberately narrow:
- preserve v61 current-proof truth synchronization if v58 is reinstalled later;
- recover original activation causality when restart file detection appended a
  FILE_SYSTEM record after an earlier heartbeat-triggered activation;
- remove the circular requirement that authority/execution readiness already be
  true while the kill switch itself is intentionally forcing them false.

v132 is chained from this canonical installer so durability ownership is always
installed after the v131 causality layer.

No generic kill-switch clearing, risk bypass, synthetic readiness, SEAK resume,
or execution-authority grant is introduced.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.readiness_killswitch_causality_v131")
MARKER = "20260817-readiness-killswitch-causality-v131"
RELEASE_ID = "20260817-runtime-convergence-v131"
_FLAG = "NIJA_READINESS_KILLSWITCH_CAUSALITY_V131_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False


def _patch_v58_precedence() -> bool:
    from bot import final_production_activation_repair_v58_patch as v58

    current = getattr(v58, "_patch_readiness", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v131_precedence", False):
        return True

    @wraps(current)
    def patch_readiness_v131() -> bool:
        try:
            from bot import final_production_activation_repair_v61_patch as v61
            if os.environ.get("NIJA_FINAL_PRODUCTION_ACTIVATION_V61_INSTALLED") == "1" or bool(
                getattr(v61, "_INSTALLED", False)
            ):
                reapply = getattr(v61, "_patch_v16_truth_sync", None)
                if callable(reapply) and bool(reapply()):
                    LOGGER.critical(
                        "READINESS_V131_V61_PRECEDENCE marker=%s v58_reinstall_blocked=true current_proof_sync=true",
                        MARKER,
                    )
                    return True
        except Exception as exc:
            LOGGER.warning("READINESS_V131_V61_PRECEDENCE_PROBE_FAILED marker=%s err=%s", MARKER, exc)
        return bool(current())

    patch_readiness_v131._nija_v131_precedence = True  # type: ignore[attr-defined]
    v58._patch_readiness = patch_readiness_v131
    return True


def _causal_activation(status: dict[str, Any]) -> tuple[str, str]:
    history = list(status.get("recent_history") or [])
    if not history:
        return "", ""

    latest = history[-1] if isinstance(history[-1], dict) else {}
    latest_reason = str(latest.get("reason") or "")
    latest_source = str(latest.get("source") or "")

    if latest_source.strip().upper() == "FILE_SYSTEM" and "Kill switch file detected" in latest_reason:
        for item in reversed(history[:-1]):
            if not isinstance(item, dict) or not item.get("source"):
                continue
            reason = str(item.get("reason") or "")
            source = str(item.get("source") or "")
            if source.strip().upper() == "FILE_SYSTEM" and "Kill switch file detected" in reason:
                continue
            return reason, source
    return latest_reason, latest_source


def _patch_v130_causality() -> bool:
    from bot import kill_switch_stale_heartbeat_recovery_v130_patch as v130

    v130._latest_activation = _causal_activation

    def runtime_proofs_healthy_v131() -> tuple[bool, str]:
        if os.environ.get("NIJA_AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129_INSTALLED") != "1":
            return False, "v129_not_installed"
        if str(os.environ.get("NIJA_CORE_THREAD_ALIVE", "")).strip().lower() not in {
            "1", "true", "yes", "on", "enabled", "y"
        }:
            return False, "core_not_alive"

        try:
            from bot.entrypoint_writer_authority import get_entrypoint_writer_authority
            writer = get_entrypoint_writer_authority()
            if writer is None or not bool(getattr(writer, "acquired", False)) or bool(getattr(writer, "lost", False)):
                return False, "writer_epoch_not_current"
            if not bool(getattr(writer, "_core_thread_registered", False)):
                return False, "core_not_registered"
        except Exception as exc:
            return False, f"writer_probe:{type(exc).__name__}"

        try:
            from bot.readiness_table import snapshot
            table = snapshot()
            required = (
                "broker_connected", "balance_hydrated", "capital_ready",
                "risk_ready", "strategy_ready", "nonce_ready", "bootstrap_ready",
            )
            missing = [key for key in required if not bool(table.get(key, False))]
            if missing:
                return False, "readiness:" + ",".join(missing)
        except Exception as exc:
            return False, f"readiness_probe:{type(exc).__name__}"

        try:
            from bot.seak_nonce_causality_v128_patch import _seak_halted
            halted, reason = _seak_halted()
            if halted:
                return False, "seak_halted:" + str(reason or "unknown")
        except Exception as exc:
            return False, f"seak_probe:{type(exc).__name__}"

        try:
            from bot.bootstrap_state_machine import get_bootstrap_fsm
            state = getattr(get_bootstrap_fsm(), "state", None)
            state_value = str(getattr(state, "value", state) or "")
            if state_value != "RUNNING_SUPERVISED":
                return False, "bootstrap:" + (state_value or "unknown")
        except Exception as exc:
            return False, f"bootstrap_probe:{type(exc).__name__}"

        return True, "ok"

    v130._runtime_proofs_healthy = runtime_proofs_healthy_v131
    LOGGER.critical(
        "KILL_SWITCH_V131_CAUSALITY_PATCHED marker=%s restart_file_record_is_persistence=true "
        "authority_execution_circularity_removed=true unrelated_stops_preserved=true",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    from bot import runtime_release_manifest_patch as manifest
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["readiness_killswitch_causality_v131"] = _FLAG
    return True


def _install_v132_durability() -> bool:
    try:
        from bot import readiness_killswitch_durability_v132_patch as v132
        installer = getattr(v132, "install", None)
        if not callable(installer):
            return False
        return bool(installer())
    except Exception as exc:
        LOGGER.critical(
            "READINESS_KILLSWITCH_DURABILITY_V132_CHAIN_FAILED marker=%s err=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc, exc_info=True,
        )
        return False


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return _install_v132_durability()
        try:
            ok = _patch_v58_precedence() and _patch_v130_causality() and _patch_release_manifest()
        except Exception as exc:
            LOGGER.critical(
                "READINESS_KILLSWITCH_CAUSALITY_V131_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc, exc_info=True,
            )
            ok = False
        if not ok:
            os.environ.pop(_FLAG, None)
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
        if not _install_v132_durability():
            os.environ.pop(_FLAG, None)
            _INSTALLED = False
            return False
        LOGGER.critical(
            "READINESS_KILLSWITCH_CAUSALITY_V131_INSTALLED marker=%s release=%s "
            "generic_auto_clear=false risk_gates_unchanged=true readiness_synthetic=false execution_authority_unchanged=true v132_chained=true",
            MARKER, RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_causal_activation"]
