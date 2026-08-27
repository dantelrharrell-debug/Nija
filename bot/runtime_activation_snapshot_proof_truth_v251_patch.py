"""Keep activation-snapshot fallback aligned with canonical readiness proof (v251).

Production on 2026-08-27 showed the capital snapshot bridge reporting that its
local concrete gates had passed and calling TradingStateMachine's compatibility
force route while canonical readiness still had ``execution_ready=False``.  The
compatibility route correctly refused the transition, but the premature request
created contradictory activation diagnostics and proof churn while the genuine
heartbeat order result was still outstanding.

This patch does not activate trading.  It only wraps the bridge's legacy
``_concrete_activation_gates_pass`` fallback predicate so that a compatibility
activation request cannot be issued until the canonical readiness table is
complete.  When heartbeat verification is required, the canonical heartbeat
marker must also be present, stage-sufficient, and fresh.  The wrapper is
periodically reasserted because older convergence installers can replace or
rebind the bridge helper later in startup.

No readiness flag, nonce, execution proof, heartbeat marker, kill switch, writer
lease, broker result, order result, or trading state is mutated here.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_activation_snapshot_proof_truth_v251")
MARKER = "20260827-activation-snapshot-proof-truth-v251"
_FLAG = "NIJA_ACTIVATION_SNAPSHOT_PROOF_TRUTH_V251_READY"
_PATCH_ATTR = "_nija_activation_snapshot_proof_truth_v251"
_IMPORT_FLAG = "_NIJA_ACTIVATION_SNAPSHOT_PROOF_TRUTH_V251_IMPORT_HOOK"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_IMPORT_LOCAL = threading.local()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _import(*names: str) -> ModuleType | None:
    for name in names:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    for name in names:
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        if isinstance(module, ModuleType):
            return module
    return None


def _canonical_readiness_complete() -> tuple[bool, str]:
    module = _import("bot.readiness_table", "readiness_table")
    if module is None:
        return False, "readiness_table_unavailable"
    snapshot_fn = getattr(module, "snapshot", None)
    if not callable(snapshot_fn):
        return False, "readiness_snapshot_unavailable"
    try:
        snapshot = dict(snapshot_fn() or {})
    except Exception as exc:
        return False, f"readiness_snapshot_error:{type(exc).__name__}:{exc}"
    if not snapshot:
        return False, "readiness_snapshot_empty"
    pending = sorted(str(key) for key, value in snapshot.items() if not bool(value))
    if pending:
        return False, f"readiness_incomplete:{','.join(pending)}"
    return True, "readiness_complete"


def _canonical_heartbeat_proof(tsm_module: Any) -> tuple[bool, str]:
    required = _truthy("HEARTBEAT_REQUIRED_FIRST_ACTIVATION") or _truthy("HEARTBEAT_TRADE")
    if not required:
        return True, "heartbeat_not_required"
    status = getattr(tsm_module, "_heartbeat_verification_status", None)
    if not callable(status):
        return False, "heartbeat_verifier_unavailable"
    try:
        ok, detail, _meta = status()
    except Exception as exc:
        return False, f"heartbeat_verifier_error:{type(exc).__name__}:{exc}"
    if not bool(ok):
        return False, f"heartbeat_verification:{str(detail or 'not_verified')}"
    return True, "heartbeat_verified"


def _patch_bridge() -> bool:
    bridge = _import("bot.activation_snapshot_bridge_patch", "activation_snapshot_bridge_patch")
    if bridge is None:
        return False
    current = getattr(bridge, "_concrete_activation_gates_pass", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def proof_truth_guard(tsm_module: Any) -> tuple[bool, str]:
        ok, detail = current(tsm_module)
        if not bool(ok):
            return False, str(detail or "bridge_gate_blocked")

        readiness_ok, readiness_detail = _canonical_readiness_complete()
        if not readiness_ok:
            LOGGER.info(
                "ACTIVATION_SNAPSHOT_V251_PROOF_PENDING marker=%s blocker=%s "
                "force_compat_not_called=true readiness_mutated=false nonce_mutated=false "
                "execution_proof_fabricated=false heartbeat_marker_written=false "
                "kill_switch_unchanged=true forced_activation=false trading_fail_closed=true",
                MARKER,
                readiness_detail,
            )
            return False, readiness_detail

        heartbeat_ok, heartbeat_detail = _canonical_heartbeat_proof(tsm_module)
        if not heartbeat_ok:
            LOGGER.info(
                "ACTIVATION_SNAPSHOT_V251_PROOF_PENDING marker=%s blocker=%s "
                "canonical_readiness_complete=true force_compat_not_called=true "
                "readiness_mutated=false nonce_mutated=false execution_proof_fabricated=false "
                "heartbeat_marker_written=false kill_switch_unchanged=true "
                "forced_activation=false trading_fail_closed=true",
                MARKER,
                heartbeat_detail,
            )
            return False, heartbeat_detail

        return True, "canonical_readiness_and_heartbeat_proof_current"

    setattr(proof_truth_guard, _PATCH_ATTR, True)
    setattr(proof_truth_guard, "__wrapped__", current)
    bridge._concrete_activation_gates_pass = proof_truth_guard
    return True


def _worker() -> None:
    while True:
        try:
            _patch_bridge()
        except Exception as exc:
            LOGGER.warning(
                "ACTIVATION_SNAPSHOT_V251_REASSERT_ERROR marker=%s err=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(1.0)


def install() -> bool:
    global _THREAD
    with _LOCK:
        # The target may not yet be imported.  Install the import hook and worker
        # first; readiness means the protection mechanism is armed, not that the
        # activation bridge is already loaded.
        if not getattr(builtins, _IMPORT_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if getattr(_IMPORT_LOCAL, "active", False):
                    return result
                text = str(name or "")
                if "activation_snapshot_bridge" in text or "trading_state_machine" in text or "readiness_table" in text:
                    _IMPORT_LOCAL.active = True
                    try:
                        _patch_bridge()
                    finally:
                        _IMPORT_LOCAL.active = False
                return result

            builtins.__import__ = guarded_import
            setattr(builtins, _IMPORT_FLAG, True)

        _patch_bridge()
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ActivationSnapshotProofTruthV251",
                daemon=True,
            )
            _THREAD.start()
        os.environ[_FLAG] = "1"

    LOGGER.critical(
        "ACTIVATION_SNAPSHOT_PROOF_TRUTH_V251_READY marker=%s ready=true "
        "canonical_readiness_required=true canonical_heartbeat_required_when_configured=true "
        "self_reasserting=true readiness_mutated=false nonce_mutated=false "
        "execution_proof_fabricated=false heartbeat_marker_written=false "
        "kill_switch_unchanged=true writer_lease_unchanged=true broker_results_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_readiness_complete",
    "_canonical_heartbeat_proof",
    "_patch_bridge",
]
