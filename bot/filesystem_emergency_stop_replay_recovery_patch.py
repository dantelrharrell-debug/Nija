from __future__ import annotations

"""Legacy filesystem EMERGENCY_STOP compatibility shim — fail closed.

The original 20260708b repair used marker/state-file text heuristics to decide
that an ``EMERGENCY_STOP`` file was a stale replay, then quarantined the marker
and reset the state machine.  Later production hardening (v130/v131/v132,
v143/v185/v186, and v193/v194) established a much narrower recovery contract:
a stop may recover automatically only when canonical provenance proves the
retired ``AUTHORITY_HEARTBEAT_EXPIRED`` + ``core_thread_dead`` race and all
current runtime health proofs pass.

This module now preserves its import/API compatibility while delegating any
recovery attempt to that guarded chain.  It never quarantines/removes an
EMERGENCY_STOP marker itself, never flips ``KillSwitch._is_active``, never
resets the state machine, never grants execution authority, and never forces
LIVE_ACTIVE.
"""

import importlib
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("nija.filesystem_emergency_stop_replay_recovery")
MARKER = "20260824-filesystem-emergency-stop-guarded-v214"
_FLAG = "NIJA_FILESYSTEM_EMERGENCY_STOP_REPLAY_GUARDED_V214_READY"


def _base_path(explicit: Any = None) -> Path:
    if explicit:
        return Path(str(explicit)).resolve()
    return Path(__file__).resolve().parents[1]


def _marker_exists(base_path: Any = None) -> bool:
    try:
        return (_base_path(base_path) / "EMERGENCY_STOP").exists()
    except Exception:
        return False


def _delegate_guarded_recovery() -> bool:
    """Delegate only to the canonical exact-provenance recovery chain."""
    try:
        v132 = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")
        attempt = getattr(v132, "_attempt_persisted_stop_recovery", None)
        if not callable(attempt):
            logger.critical(
                "FILESYSTEM_EMERGENCY_STOP_V214_PRESERVED marker=%s "
                "reason=canonical_recovery_unavailable marker_removed=false "
                "state_mutated=false trading_fail_closed=true",
                MARKER,
            )
            return False
        recovered = bool(attempt())
        logger.critical(
            "FILESYSTEM_EMERGENCY_STOP_V214_DELEGATED marker=%s recovered=%s "
            "canonical_v132_v143_v193_only=true marker_removed_directly=false "
            "state_mutated_directly=false generic_text_heuristics=false",
            MARKER,
            str(recovered).lower(),
        )
        return recovered
    except Exception as exc:
        logger.warning(
            "FILESYSTEM_EMERGENCY_STOP_V214_DELEGATE_ERROR marker=%s err=%s:%s "
            "trading_fail_closed=true marker_removed=false state_mutated=false",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def recover(base_path: Any = None) -> bool:
    """Compatibility recovery entry point with guarded-only semantics.

    No text-based auto-clear is permitted.  If no marker exists there is
    nothing to recover.  If a marker exists, the canonical v132/v143/v193 chain
    owns the decision.
    """
    if not _marker_exists(base_path):
        return False
    return _delegate_guarded_recovery()


def install_import_hook() -> bool:
    # Explicitly disable the historical broad heuristic switch even if an old
    # deployment environment still carries it as true.  The compatibility
    # module remains installed, but all recovery is delegated to canonical
    # exact provenance.
    os.environ["NIJA_FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_ENABLED"] = "false"
    os.environ[_FLAG] = "1"
    logger.critical(
        "FILESYSTEM_EMERGENCY_STOP_REPLAY_GUARDED_V214_READY marker=%s "
        "legacy_text_auto_clear=false quarantine_direct=false state_reset_direct=false "
        "canonical_guarded_recovery_only=true manual_ui_cli_risk_stops_preserved=true "
        "execution_authority_unchanged=true forced_activation=false "
        "safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "recover", "install", "install_import_hook"]
