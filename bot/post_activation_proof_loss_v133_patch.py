"""Fail closed when critical current proofs are lost after LIVE_ACTIVE.

v133 keeps current readiness truth authoritative while avoiding repeated
CRITICAL telemetry for unchanged pre-live/pending state. A real loss of proof
from LIVE_ACTIVE still transitions through the canonical FSM to OFF and remains
CRITICAL.
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
_LAST_SYNC_SIGNATURE = ""

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
    global _LAST_SYNC_SIGNATURE
    table = importlib.import_module("bot.readiness_table")
    before = dict(table.snapshot())
    sm = _state_machine()
    state_before = _state_value(sm)

    after, pending = _revoke_false_readiness(proofs)
    failed_closed = _fail_closed_live_state(sm, pending)
    state_after = _state_value(sm)

    signature = f"{state_before}|{state_after}|{pending}|{before != after}|{failed_closed}"
    changed_signature = signature != _LAST_SYNC_SIGNATURE
    _LAST_SYNC_SIGNATURE = signature

    if failed_closed:
        LOGGER.critical(
            "PREACTIVATION_READINESS_V133_TRUTH_SYNC marker=%s state_before=%s state_after=%s "
            "pending=%s fail_closed_transition=true",
            MARKER,
            state_before,
            state_after,
            pending,
        )
    elif before != after or changed_signature:
        LOGGER.info(
            "PREACTIVATION_READINESS_V133_TRUTH_SYNC marker=%s state_before=%s state_after=%s "
            "pending=%s table_changed=%s fail_closed_transition=false",
            MARKER,
            state_before,
            state_after,
            pending,
            str(before != after).lower(),
        )
    else:
        LOGGER.debug(
            "PREACTIVATION_READINESS_V133_UNCHANGED marker=%s state=%s pending=%s",
            MARKER,
            state_after,
            pending,
        )
    return (not pending), pending


_truth_sync_v133._nija_v61_truth_sync = True  # type: ignore[attr-defined]
_truth_sync_v133._nija_v132_truth_sync = True  # type: ignore[attr-defined]
_truth_sync_v133._nija_v133_truth_sync = True  # type: ignore[attr-defined]


def _anchor_owner() -> bool:
    v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    v58 = importlib.import_module("bot.final_production_activation_repair_v58_patch")
    v132 = importlib.import_module("bot.readiness_killswitch_durability_v132_patch")

    v132._durable_truth_sync = _truth_sync_v133
    v58._incremental_mark_proven_readiness = _truth_sync_v133
    v16._mark_proven_readiness = _truth_sync_v133

    original_patch = getattr(v58, "_patch_readiness", None)
    if callable(original_patch) and not getattr(original_patch, "_nija_v133_owner", False):
        def patch_readiness_v133() -> bool:
            v132._durable_truth_sync = _truth_sync_v133
            v58._incremental_mark_proven_readiness = _truth_sync_v133
            v16._mark_proven_readiness = _truth_sync_v133
            LOGGER.debug(
                "READINESS_V133_OWNER_REASSERTED marker=%s source=v58_patch_readiness post_activation_fail_closed=true",
                MARKER,
            )
            return True
        patch_readiness_v133._nija_v133_owner = True  # type: ignore[attr-defined]
        v58._patch_readiness = patch_readiness_v133

    LOGGER.info(
        "READINESS_V133_OWNER_ANCHORED marker=%s v132_export_replaced=true v58_export_replaced=true v16_owner=true post_activation_fail_closed=true",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["post_activation_proof_loss_v133"] = _FLAG
    # Register proof only. Older convergence modules must never downgrade the
    # canonical release identity owned by the newest manifest.
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
                "POST_ACTIVATION_PROOF_LOSS_V133_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
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
        LOGGER.info(
            "POST_ACTIVATION_PROOF_LOSS_V133_INSTALLED marker=%s post_activation_false_proofs_revoke_readiness=true canonical_off_transition=true kill_switch_unchanged=true seak_unchanged=true nonce_gates_unchanged=true risk_gates_unchanged=true force_live=false",
            MARKER,
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
