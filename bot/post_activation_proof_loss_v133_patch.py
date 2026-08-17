"""Fail closed when critical current proofs are lost after LIVE_ACTIVE.

v133 closes the post-activation gap exposed by v132: v132 detected false
current proofs while LIVE_ACTIVE but intentionally left the readiness table
sticky after activation.  That allowed the public trading state to remain live
while broker/balance/capital truth had already fallen false.

Safety contract:
- never fabricate or copy readiness from coarse/sticky state;
- never clear kill switch or SEAK;
- never grant writer, nonce, or execution authority;
- never force LIVE_ACTIVE;
- use the canonical TradingStateMachine transition for LIVE_ACTIVE -> OFF so
  activation commitment, dispatch permission, and execution authority are
  revoked atomically by the existing state machine;
- leave recovery/reactivation to the existing canonical activation path after
  all current proofs become true again.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.post_activation_proof_loss_v133")
MARKER = "20260817-post-activation-proof-loss-v133"
RELEASE_ID = "20260817-runtime-convergence-v133"
_FLAG = "NIJA_POST_ACTIVATION_PROOF_LOSS_V133_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False

_CRITICAL_KEYS = (
    "broker_connected",
    "balance_hydrated",
    "authority_ready",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "execution_ready",
    "nonce_ready",
    "bootstrap_ready",
)


def _state_machine() -> Any:
    monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
    return monitor._state_machine()


def _state_value(sm: Any | None = None) -> str:
    try:
        machine = sm if sm is not None else _state_machine()
        if machine is None:
            return "UNAVAILABLE"
        state = machine.get_current_state()
        return str(getattr(state, "value", state) or "UNAVAILABLE").strip().upper()
    except Exception:
        return "UNAVAILABLE"


def _revoke_false_readiness(proofs: dict[str, bool]) -> tuple[dict[str, bool], list[str]]:
    table = importlib.import_module("bot.readiness_table")
    for key in _CRITICAL_KEYS:
        if bool(proofs.get(key, False)):
            table.mark_ready(key)
        else:
            table.revoke_ready(key, reason="v133_current_proof_false")
    after = dict(table.snapshot())
    pending = [key for key in _CRITICAL_KEYS if not bool(proofs.get(key, False))]
    os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "1" if not pending else "0"
    return after, pending


def _fail_closed_live_state(sm: Any, pending: list[str]) -> bool:
    """Route LIVE_ACTIVE -> OFF through the canonical FSM when proofs are lost."""
    if _state_value(sm) != "LIVE_ACTIVE" or not pending:
        return False

    reason = "v133 current proof loss: " + ",".join(pending)
    try:
        tsm = importlib.import_module("bot.trading_state_machine")
        trading_state = getattr(tsm, "TradingState")
        sm.transition_to(trading_state.OFF, reason=reason)
    except Exception as exc:
        # Do not invent a secondary state mutation if the canonical transition
        # fails.  Emit a hard diagnostic; existing dispatch gates still observe
        # the revoked readiness table and false readiness env.
        LOGGER.critical(
            "POST_ACTIVATION_PROOF_LOSS_V133_TRANSITION_FAILED marker=%s pending=%s "
            "err=%s:%s canonical_state_unchanged=true trading_fail_closed_requested=true",
            MARKER,
            pending,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False

    LOGGER.critical(
        "POST_ACTIVATION_PROOF_LOSS_V133_FAIL_CLOSED marker=%s pending=%s "
        "transition=LIVE_ACTIVE->OFF execution_authority_revoked_by_fsm=true "
        "dispatch_revoked_by_fsm=true reactivation_requires_canonical_commit=true",
        MARKER,
        pending,
    )
    return True


def _truth_sync_v133(proofs: dict[str, bool]) -> tuple[bool, list[str]]:
    table = importlib.import_module("bot.readiness_table")
    before = dict(table.snapshot())
    sm = _state_machine()
    state_before = _state_value(sm)

    after, pending = _revoke_false_readiness(proofs)
    failed_closed = _fail_closed_live_state(sm, pending)
    state_after = _state_value(sm)

    LOGGER.critical(
        "PREACTIVATION_READINESS_V133_TRUTH_SYNC marker=%s state_before=%s state_after=%s "
        "before=%s after=%s pending=%s fail_closed_transition=%s",
        MARKER,
        state_before,
        state_after,
        before,
        after,
        pending,
        str(failed_closed).lower(),
    )
    return (not pending), pending


# Keep compatibility ownership markers so v132's durability watchdog does not
# replace this stricter successor with the older pre-live-only function.
_truth_sync_v133._nija_v61_truth_sync = True  # type: ignore[attr-defined]
_truth_sync_v133._nija_v132_truth_sync = True  # type: ignore[attr-defined]
_truth_sync_v133._nija_v133_truth_sync = True  # type: ignore[attr-defined]


def _anchor_owner() -> bool:
    v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    v58 = importlib.import_module("bot.final_production_activation_repair_v58_patch")
    v132 = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")

    # Replace every compatibility export that can be replayed later.
    v132._durable_truth_sync = _truth_sync_v133
    v58._incremental_mark_proven_readiness = _truth_sync_v133
    v16._mark_proven_readiness = _truth_sync_v133

    original_patch = getattr(v58, "_patch_readiness", None)
    if callable(original_patch) and not getattr(original_patch, "_nija_v133_owner", False):
        def patch_readiness_v133() -> bool:
            v132._durable_truth_sync = _truth_sync_v133
            v58._incremental_mark_proven_readiness = _truth_sync_v133
            v16._mark_proven_readiness = _truth_sync_v133
            LOGGER.critical(
                "READINESS_V133_OWNER_REASSERTED marker=%s source=v58_patch_readiness "
                "post_activation_fail_closed=true",
                MARKER,
            )
            return True
        patch_readiness_v133._nija_v133_owner = True  # type: ignore[attr-defined]
        v58._patch_readiness = patch_readiness_v133

    LOGGER.critical(
        "READINESS_V133_OWNER_ANCHORED marker=%s v132_export_replaced=true "
        "v58_export_replaced=true v16_owner=true post_activation_fail_closed=true",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["post_activation_proof_loss_v133"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        try:
            ok = _anchor_owner() and _patch_release_manifest()
        except Exception as exc:
            LOGGER.critical(
                "POST_ACTIVATION_PROOF_LOSS_V133_INSTALL_FAILED marker=%s err=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ok = False
        if not ok:
            os.environ.pop(_FLAG, None)
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "POST_ACTIVATION_PROOF_LOSS_V133_INSTALLED marker=%s release=%s "
            "post_activation_false_proofs_revoke_readiness=true canonical_off_transition=true "
            "kill_switch_unchanged=true seak_unchanged=true nonce_gates_unchanged=true "
            "risk_gates_unchanged=true force_live=false",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_truth_sync_v133",
    "_revoke_false_readiness",
    "_fail_closed_live_state",
    "_anchor_owner",
]
