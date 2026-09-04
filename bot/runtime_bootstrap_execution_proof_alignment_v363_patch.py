"""Align BootstrapFSM execution authority with canonical execution proof (v363).

Fresh production evidence on 2026-09-04 showed BootstrapFSM reporting
``execution_authority=True`` while the canonical readiness table correctly had
``execution_ready=False`` because no broker-confirmed fill had produced fresh
execution proof.  v361 and v362 kept activation fail-closed, but the bootstrap
compatibility authority surface remained stale and is consumed by legacy
execution-contract repair code.

v363 makes BootstrapFSM execution authority an *effective* authority: the raw
bootstrap RUNNING_SUPERVISED latch is necessary but not sufficient.  Canonical
``execution_ready`` must also be true.  It additionally gates
``execution_contract_authority.authority_proof`` so snapshot repair cannot
promote runtime dispatch without canonical proof.

This patch never writes execution readiness or proof, never treats ACK/order
acceptance as a fill, and never forces activation.  Writer, nonce, risk,
capital, position-sync, ECEL, broker-health, minimum-order, fill-verification,
kill-switch, rejection, quantity, and protective-exit gates are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_bootstrap_execution_proof_alignment_v363")
MARKER = "20260904-runtime-bootstrap-execution-proof-alignment-v363"
_READY_FLAG = "NIJA_RUNTIME_BOOTSTRAP_EXECUTION_PROOF_ALIGNMENT_V363_READY"
_PATCH_ATTR = "_nija_bootstrap_execution_proof_alignment_v363"
_LOCK = threading.RLock()


def _canonical_execution_ready() -> tuple[bool, str]:
    """Observe canonical execution readiness without mutating it."""
    try:
        try:
            readiness = importlib.import_module("bot.readiness_table")
        except ImportError:
            readiness = importlib.import_module("readiness_table")
        snapshot = getattr(readiness, "snapshot", None)
        if not callable(snapshot):
            return False, "readiness_snapshot_unavailable"
        table = dict(snapshot() or {})
        ready = bool(table.get("execution_ready", False))
        return ready, "canonical_execution_ready" if ready else "canonical_execution_proof_pending"
    except Exception as exc:
        return False, f"readiness_snapshot_error:{type(exc).__name__}"


def _effective_bootstrap_authority(fsm: Any) -> tuple[bool, str]:
    """Return effective bootstrap authority, fail-closed on missing proof."""
    lock = getattr(fsm, "_lock", None)
    try:
        if lock is not None:
            with lock:
                raw = bool(getattr(fsm, "_execution_authority", False))
        else:
            raw = bool(getattr(fsm, "_execution_authority", False))
    except Exception as exc:
        return False, f"bootstrap_authority_read_error:{type(exc).__name__}"

    if not raw:
        return False, "bootstrap_execution_authority_false"
    proof_ready, proof_detail = _canonical_execution_ready()
    if not proof_ready:
        return False, proof_detail
    return True, "bootstrap_and_canonical_execution_ready"


def _patch_bootstrap_fsm() -> bool:
    module = importlib.import_module("bot.bootstrap_state_machine")
    cls = getattr(module, "BootstrapStateMachine", None)
    if cls is None:
        return False

    prop = cls.__dict__.get("execution_authority")
    current_has = getattr(cls, "has_execution_authority", None)
    if not isinstance(prop, property) or not callable(prop.fget) or not callable(current_has):
        return False

    if not bool(getattr(prop.fget, _PATCH_ATTR, False)):
        original_getter = prop.fget

        def execution_authority_v363(self: Any) -> bool:
            # Preserve the original raw-latch read for compatibility, then require
            # canonical fill-derived execution readiness before exposing authority.
            raw = bool(original_getter(self))
            if not raw:
                return False
            proof_ready, proof_detail = _canonical_execution_ready()
            if not proof_ready:
                LOGGER.info(
                    "BOOTSTRAP_EXECUTION_AUTHORITY_V363_DEFERRED marker=%s detail=%s "
                    "raw_bootstrap_authority=true effective_authority=false "
                    "execution_ready_unchanged=true execution_proof_fabricated=false safety_gates_bypassed=false",
                    MARKER,
                    proof_detail,
                )
                return False
            return True

        setattr(execution_authority_v363, _PATCH_ATTR, True)
        cls.execution_authority = property(
            execution_authority_v363,
            prop.fset,
            prop.fdel,
            prop.__doc__,
        )

    current_has = getattr(cls, "has_execution_authority", None)
    if callable(current_has) and not bool(getattr(current_has, _PATCH_ATTR, False)):
        def has_execution_authority_v363(self: Any) -> bool:
            return bool(self.execution_authority)

        setattr(has_execution_authority_v363, _PATCH_ATTR, True)
        cls.has_execution_authority = has_execution_authority_v363

    return True


def _patch_execution_contract_authority() -> bool:
    module = importlib.import_module("bot.execution_contract_authority")
    current = getattr(module, "authority_proof", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    original = current

    def authority_proof_v363(*args: Any, **kwargs: Any) -> tuple[bool, str]:
        proof_ready, proof_detail = _canonical_execution_ready()
        if not proof_ready:
            return False, proof_detail
        return original(*args, **kwargs)

    setattr(authority_proof_v363, _PATCH_ATTR, True)
    setattr(authority_proof_v363, "__wrapped__", original)
    module.authority_proof = authority_proof_v363
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if isinstance(required, dict):
            required["runtime_bootstrap_execution_proof_alignment_v363"] = _READY_FLAG
            return True
    except Exception:
        pass
    return False


def install_import_hook() -> bool:
    with _LOCK:
        try:
            ok = bool(
                _patch_bootstrap_fsm()
                and _patch_execution_contract_authority()
                and _patch_release_manifest()
            )
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_BOOTSTRAP_EXECUTION_PROOF_ALIGNMENT_V363_INSTALL_FAILED marker=%s err=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            ok = False
        os.environ[_READY_FLAG] = "1" if ok else "0"
        if ok:
            LOGGER.critical(
                "RUNTIME_BOOTSTRAP_EXECUTION_PROOF_ALIGNMENT_V363_READY marker=%s ready=true "
                "bootstrap_execution_authority_requires_canonical_execution_ready=true "
                "execution_contract_snapshot_repair_requires_canonical_execution_ready=true "
                "raw_supervised_latch_not_execution_proof=true ack_not_fill=true "
                "execution_ready_unchanged=true execution_proof_fabricated=false forced_activation=false "
                "writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_order_fill_gates_unchanged=true "
                "kill_switch_unchanged=true rejection_latches_unchanged=true exit_quantities_unchanged=true "
                "take_profit_preserved=true stop_loss_preserved=true trailing_take_profit_preserved=true "
                "trailing_stop_preserved=true auto_exit_reconciler_preserved=true safety_gates_bypassed=false",
                MARKER,
            )
        return ok


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_execution_ready",
    "_effective_bootstrap_authority",
    "_patch_bootstrap_fsm",
    "_patch_execution_contract_authority",
]
