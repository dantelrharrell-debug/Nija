"""Canonical supervised-thread proof repair v359.

The canonical startup already registers the real TradingLoop with the exact
writer authority before BootstrapFSM finalization.  The legacy publisher then
looked only at ``runtime._heartbeat_thread``.  In the prebot-adopted runtime
that private pointer can be absent even while the writer lease is genuinely
renewing and the registered core thread is alive, causing a false fatal
startup failure immediately after successful core registration.

v359 keeps startup fail-closed and replaces that stale private-pointer test
with stronger current evidence:
- exact writer runtime is acquired and not lost;
- writer lease-renewal health is current;
- the writer authority reports a registered, alive canonical core thread;
- only then is supervised-worker evidence recorded.

This patch does not grant execution authority, fabricate fill/capital proof,
change trading state, alter positions/exits, or bypass activation gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_supervised_thread_proof_v359")
MARKER = "20260903-runtime-supervised-thread-proof-v359"
_READY_FLAG = "NIJA_RUNTIME_SUPERVISED_THREAD_PROOF_V359_READY"
_LOCK = threading.RLock()


def _writer_core_supervision_proof(runtime: Any) -> tuple[bool, str]:
    if runtime is None:
        return False, "runtime_missing"
    if not bool(getattr(runtime, "acquired", False)):
        return False, "writer_not_acquired"
    if bool(getattr(runtime, "lost", True)):
        return False, "writer_lost"

    renewal = getattr(runtime, "_nija_lease_renewal_health", None)
    if not callable(renewal):
        return False, "renewal_health_unavailable"
    try:
        health = renewal()
        renewal_ok = bool(health[0]) if isinstance(health, (tuple, list)) and health else bool(health)
    except Exception as exc:
        return False, f"renewal_health_error:{type(exc).__name__}"
    if not renewal_ok:
        return False, "renewal_unhealthy"

    status = getattr(runtime, "_core_thread_status", None)
    if callable(status):
        try:
            registered, alive, reason = status()
        except Exception as exc:
            return False, f"core_status_error:{type(exc).__name__}"
        if not bool(registered):
            return False, f"core_not_registered:{reason}"
        if not bool(alive):
            return False, f"core_not_alive:{reason}"
        return True, "writer_renewal_and_registered_core_current"

    # Compatibility fallback remains strict: both the registration bit and
    # the concrete thread's liveness must be present.
    core = getattr(runtime, "_core_thread", None)
    registered = bool(getattr(runtime, "_core_thread_registered", False))
    alive_reader = getattr(core, "is_alive", None)
    try:
        alive = bool(alive_reader()) if callable(alive_reader) else False
    except Exception:
        alive = False
    if registered and alive:
        return True, "writer_renewal_and_registered_core_compat"
    return False, "registered_core_proof_unavailable"


def _patch_bot_main() -> bool:
    bot_main = importlib.import_module("bot.bot_main")
    current = getattr(bot_main, "_publish_supervised_thread_evidence", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v359_supervised_thread_proof", False):
        return True

    def publish_supervised_thread_evidence_v359() -> bool:
        runtime = getattr(bot_main, "_writer_authority_runtime", None)
        ok, detail = _writer_core_supervision_proof(runtime)
        if not ok:
            LOGGER.critical(
                "SUPERVISED_THREAD_EVIDENCE_V359_BLOCKED marker=%s detail=%s activation_remains_pending=true forced_activation=false safety_gates_bypassed=false",
                MARKER,
                detail,
            )
            return False

        try:
            from bot.startup_coordinator import get_startup_coordinator

            coordinator = get_startup_coordinator()
            live_workers = sum(
                1
                for worker in threading.enumerate()
                if worker is not threading.current_thread() and worker.is_alive()
            )
            worker_count = max(1, live_workers)
            coordinator.record_threads_supervised(
                worker_count,
                bootstrap_state="RUNNING_SUPERVISED",
            )
            LOGGER.critical(
                "SUPERVISED_THREAD_EVIDENCE_V359_PUBLISHED marker=%s workers=%d detail=%s exact_writer_current=true renewal_healthy=true registered_core_alive=true heartbeat_private_pointer_not_required=true execution_authority_granted=false execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
                worker_count,
                detail,
            )
            return True
        except Exception as exc:
            LOGGER.exception(
                "SUPERVISED_THREAD_EVIDENCE_V359_FAILED marker=%s err=%s:%s activation_remains_pending=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

    publish_supervised_thread_evidence_v359._nija_v359_supervised_thread_proof = True
    publish_supervised_thread_evidence_v359.__wrapped__ = current
    bot_main._publish_supervised_thread_evidence = publish_supervised_thread_evidence_v359
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if isinstance(required, dict):
            required["runtime_supervised_thread_proof_v359"] = _READY_FLAG
            return True
    except Exception:
        pass
    return False


def install_import_hook() -> bool:
    with _LOCK:
        try:
            ok = bool(_patch_bot_main() and _patch_release_manifest())
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_SUPERVISED_THREAD_PROOF_V359_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            ok = False
        os.environ[_READY_FLAG] = "1" if ok else "0"
        if ok:
            LOGGER.critical(
                "RUNTIME_SUPERVISED_THREAD_PROOF_V359_READY marker=%s ready=true exact_writer_required=true renewal_health_required=true registered_core_alive_required=true execution_authority_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
            )
        return ok


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_writer_core_supervision_proof"]
