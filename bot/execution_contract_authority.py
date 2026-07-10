"""Writer-authority proof and per-dispatch snapshot pinning."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import is_dataclass, replace
from typing import Any

from .execution_contract_primitives import MARKER, number, truthy

logger = logging.getLogger("nija.execution_contract_authority")


def authority_proof() -> tuple[bool, str]:
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    heartbeat_ts = number(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS"))
    required = {
        "live_capital": truthy("LIVE_CAPITAL_VERIFIED"),
        "runtime_authority": truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY"),
        "heartbeat_active": str(os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", "")) == "1",
        "fencing_token": bool(str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()),
        "lease_generation": number(generation) > 0,
        "heartbeat_timestamp": heartbeat_ts > 0,
    }
    if truthy("DRY_RUN_MODE") or truthy("PAPER_MODE"):
        return False, "simulation_mode"
    missing = [name for name, ok in required.items() if not ok]
    if missing:
        return False, "missing:" + ",".join(missing)
    max_age = max(5.0, number(os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S"), 90.0))
    age = max(0.0, time.time() - heartbeat_ts)
    if age > max_age:
        return False, f"heartbeat_stale:age_s={age:.1f}:max_age_s={max_age:.1f}"
    try:
        from bot.kill_switch import get_kill_switch
        if bool(get_kill_switch().is_active()):
            return False, "kill_switch_active"
    except Exception as exc:
        return False, f"kill_switch_probe_failed:{exc}"
    try:
        from bot.bootstrap_state_machine import get_bootstrap_fsm
        fsm = get_bootstrap_fsm()
        has_auth = fsm.has_execution_authority() if hasattr(fsm, "has_execution_authority") else bool(getattr(fsm, "execution_authority", False))
        if not has_auth:
            return False, "bootstrap_execution_authority_false"
    except Exception as exc:
        return False, f"bootstrap_authority_unavailable:{exc}"
    try:
        from bot.execution_authority_context import assert_distributed_writer_authority
        assert_distributed_writer_authority()
    except Exception as exc:
        return False, f"distributed_writer_not_ready:{exc}"
    return True, f"writer_lineage_verified:generation={generation}:heartbeat_age_s={age:.1f}"


def repair_snapshot(snapshot: Any) -> Any:
    if bool(getattr(snapshot, "ready", False)) and bool(getattr(snapshot, "dispatch_enabled", True)):
        return snapshot
    ok, reason = authority_proof()
    if not ok:
        return snapshot
    updates = {
        "ready": True, "authority_ready": True, "nonce_ready": True,
        "dispatch_health_ready": True, "dispatch_enabled": True,
        "kill_switch_active": False, "coordinator_state": "RUN_READY",
        "runtime_state": "LIVE_ACTIVE", "reason": f"authority_snapshot_repaired:{reason}:{MARKER}",
        "lifecycle_phase": "LIVE",
    }
    if is_dataclass(snapshot):
        try:
            snapshot = replace(snapshot, **updates)
        except Exception:
            pass
    else:
        for key, value in updates.items():
            try:
                setattr(snapshot, key, value)
            except Exception:
                pass
    logger.critical("EXECUTION_AUTHORITY_SNAPSHOT_PINNED marker=%s proof=%s", MARKER, reason)
    return snapshot
