"""Repair the pre-activation authority/execution readiness cycle, fail-closed.

v153's structural authority gate included ``execution_ready`` as a prerequisite.
The canonical preactivation proof defines ``execution_ready`` using
``authority_ready``. Requiring both before authority convergence creates a
cycle in which neither proof can become true.

This patch removes only ``execution_ready`` from the *pre-authority structural*
blocker set. It does not activate trading, clear/deactivate the kill switch,
change risk policy, mark authority/execution ready, transition the trading FSM,
or dispatch broker orders. The existing authority convergence path remains
responsible for kill-switch, capital, writer/nonce and activation checks.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nija.runtime_execution_recovery_v154")
_MARKER = "20260819-runtime-execution-recovery-v154"
_PATCH_ATTR = "_nija_runtime_execution_recovery_v154"

# Proofs that are structurally independent of runtime authority. Writer/nonce
# are checked by canonical authority convergence. execution_ready is excluded
# because its canonical preactivation definition depends on authority_ready.
_REQUIRED_PRE_AUTHORITY = (
    "broker_connected",
    "balance_hydrated",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "bootstrap_ready",
)


def _safe_structural_blockers() -> list[str]:
    """Return only authority-independent structural blockers.

    Failure to read readiness truth is itself a blocker. Position-sync remains
    required whenever that proof is published by the runtime.
    """
    try:
        try:
            from bot import readiness_table
        except ImportError:
            import readiness_table  # type: ignore[import,no-redef]
        table = dict(readiness_table.snapshot())
    except Exception as exc:
        logger.warning(
            "V154_READINESS_TABLE_UNAVAILABLE marker=%s error=%s:%s trading_fail_closed=true",
            _MARKER,
            type(exc).__name__,
            exc,
        )
        return ["readiness_table_unavailable"]

    required = list(_REQUIRED_PRE_AUTHORITY)
    if "position_sync_ready" in table:
        required.append("position_sync_ready")
    return [name for name in required if not bool(table.get(name, False))]


def _install_structural_gate_repair() -> bool:
    """Replace only v153's circular structural-blocker helper."""
    try:
        from bot import kill_switch_coordinator_sync_patch as sync_patch
    except ImportError:
        import kill_switch_coordinator_sync_patch as sync_patch  # type: ignore[import,no-redef]

    current = getattr(sync_patch, "_structural_readiness_blockers", None)
    if not callable(current):
        logger.error(
            "V154_STRUCTURAL_GATE_MISSING marker=%s trading_fail_closed=true",
            _MARKER,
        )
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    def structural_readiness_blockers_v154() -> list[str]:
        blockers = _safe_structural_blockers()
        if blockers:
            logger.info(
                "V154_PRE_AUTHORITY_BLOCKED marker=%s blockers=%s activation_attempted=false trading_fail_closed=true",
                _MARKER,
                blockers,
            )
        return blockers

    setattr(structural_readiness_blockers_v154, _PATCH_ATTR, True)
    setattr(structural_readiness_blockers_v154, "__wrapped__", current)
    sync_patch._structural_readiness_blockers = structural_readiness_blockers_v154
    logger.critical(
        "V154_STRUCTURAL_GATE_REPAIRED marker=%s execution_ready_removed_from_pre_authority_gate=true safety_gates_unchanged=true",
        _MARKER,
    )
    return True


def status() -> dict[str, Any]:
    """Return diagnostic truth without mutating trading state."""
    try:
        from bot import kill_switch_coordinator_sync_patch as sync_patch
    except ImportError:
        import kill_switch_coordinator_sync_patch as sync_patch  # type: ignore[import,no-redef]
    current = getattr(sync_patch, "_structural_readiness_blockers", None)
    return {
        "marker": _MARKER,
        "installed": bool(callable(current) and getattr(current, _PATCH_ATTR, False)),
        "blockers": _safe_structural_blockers(),
        "live_activation_performed": False,
        "kill_switch_modified": False,
    }


def install() -> bool:
    return _install_structural_gate_repair()


__all__ = ["install", "status", "_safe_structural_blockers"]
