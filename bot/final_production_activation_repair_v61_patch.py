"""Production activation sequencing/readiness truth repair v61.

Post-v60 production proved the non-blocking single-flight activation worker works,
but also exposed two fail-closed correctness defects:

1. activation could be requested before the canonical core was registered and
   BootstrapFSM reached RUNNING_SUPERVISED, causing premature nonce/SEAK probes;
2. the preactivation readiness table was monotonic-true and could retain stale
   True values after current authority/nonce/execution/bootstrap proofs became
   false.

v61 fixes those defects without clearing SEAK, relaxing nonce/risk/strategy
requirements, or forcing activation/trades. It intentionally installs before
v59/v60 monitor activation so the guards are present before those monitors can
request a commit.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

logger = logging.getLogger("nija.final_production_activation_repair_v61")
MARKER = "20260812-final-production-activation-v61"
_KEYS = (
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
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value if value not in (None, "") else default))
    except Exception:
        return default


def _state_value() -> str:
    try:
        monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
        sm = monitor._state_machine()
        if sm is None:
            return "UNAVAILABLE"
        state = sm.get_current_state()
        return str(getattr(state, "value", state) or "UNAVAILABLE").strip().upper()
    except Exception:
        return "UNAVAILABLE"


def _canonical_core_bootstrap_status() -> tuple[bool, list[str], dict[str, Any]]:
    """Return non-I/O canonical writer/core/bootstrap prerequisites."""
    blockers: list[str] = []
    details: dict[str, Any] = {}
    runtime = None
    try:
        authority = importlib.import_module("bot.entrypoint_writer_authority")
        getter = getattr(authority, "get_entrypoint_writer_authority", None)
        runtime = getter() if callable(getter) else None
    except Exception as exc:
        details["writer_error"] = f"{type(exc).__name__}:{exc}"

    acquired = bool(runtime is not None and getattr(runtime, "acquired", False))
    lost = bool(runtime is not None and getattr(runtime, "lost", False))
    details["writer_acquired"] = acquired
    details["writer_lost"] = lost
    details["generation"] = getattr(runtime, "_generation", 0) if runtime is not None else 0
    if not acquired or lost:
        blockers.append("writer_epoch_current")

    core = getattr(runtime, "_core_thread", None) if runtime is not None else None
    registered = bool(runtime is not None and getattr(runtime, "_core_thread_registered", False))
    alive = False
    if core is not None and callable(getattr(core, "is_alive", None)):
        try:
            alive = bool(core.is_alive())
        except Exception:
            alive = False
    details["core_registered"] = registered
    details["core_alive"] = alive
    details["core_name"] = getattr(core, "name", "none") if core is not None else "none"
    if not registered:
        blockers.append("core_registered")
    if not alive:
        blockers.append("core_alive")

    bootstrap_state = "UNAVAILABLE"
    try:
        bootstrap = importlib.import_module("bot.bootstrap_state_machine")
        fsm = bootstrap.get_bootstrap_fsm()
        state = getattr(fsm, "state", None)
        bootstrap_state = str(getattr(state, "value", state) or "UNAVAILABLE").strip().upper()
    except Exception as exc:
        details["bootstrap_error"] = f"{type(exc).__name__}:{exc}"
    details["bootstrap_state"] = bootstrap_state
    if bootstrap_state != "RUNNING_SUPERVISED":
        blockers.append(f"bootstrap_state:{bootstrap_state}")

    try:
        bot_main = importlib.import_module("bot.bot_main")
        shutdown = getattr(bot_main, "_shutdown_event", None)
        if shutdown is not None and callable(getattr(shutdown, "is_set", None)) and shutdown.is_set():
            blockers.append("shutdown_requested")
    except Exception:
        pass

    return not blockers, blockers, details


def _seak_status() -> tuple[bool, str]:
    """Observe SEAK only. v61 never clears or mutates the halt."""
    try:
        module = importlib.import_module("bot.single_execution_authority_kernel")
        getter = getattr(module, "get_single_execution_authority_kernel", None)
        seak = getter() if callable(getter) else None
        if seak is None:
            return False, "seak_unavailable"
        halted = bool(getattr(seak, "is_halted", False))
        reason = str(getattr(seak, "halt_reason", "") or "")
        return halted, reason
    except Exception as exc:
        return False, f"seak_probe_failed:{type(exc).__name__}:{exc}"


def _safe_partial_proofs(v16: Any, blockers: list[str]) -> tuple[dict[str, bool], dict[str, Any]]:
    """Collect pre-core proofs without writer/nonce/SEAK execution probes."""
    capital = v16._capital_snapshot()
    try:
        kill_ok, kill_detail = v16._kill_switch_clear()
    except Exception as exc:
        kill_ok, kill_detail = False, f"kill_switch_probe_failed:{exc}"
    try:
        strategy = bool(v16._strategy_published())
    except Exception:
        strategy = False
    try:
        pipeline = bool(v16._execution_pipeline_ready())
    except Exception:
        pipeline = False

    hydrated = bool(capital.get("hydrated")) and not bool(capital.get("stale"))
    funded = _float(capital.get("real")) > 0.0
    registered = _int(capital.get("registered")) > 0
    risk = bool(
        _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY")
        and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED")
        and _truthy("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED")
    )
    live_mode = bool(
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )
    proofs = {
        "broker_connected": bool(hydrated and funded and registered),
        "balance_hydrated": hydrated,
        "authority_ready": False,
        "capital_ready": bool(live_mode and hydrated and funded),
        "risk_ready": risk,
        "strategy_ready": strategy,
        "execution_ready": False,
        "nonce_ready": False,
        "bootstrap_ready": False,
    }
    details = {
        "capital": capital,
        "kill_switch": kill_detail or ("clear" if kill_ok else "blocked"),
        "live_mode": live_mode,
        "execution_pipeline_wired": pipeline,
        "strict_authority": "deferred_until_canonical_core_supervised",
        "bootstrap_missing": blockers,
        "v61_precore_safe_probe": True,
    }
    return proofs, details


def _patch_v16_proof_collection() -> bool:
    v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    current = getattr(v16, "_collect_proofs", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v61_precore_safe", False):
        return True

    def collect_proofs() -> tuple[dict[str, bool], dict[str, Any]]:
        ready, blockers, details = _canonical_core_bootstrap_status()
        if not ready:
            proofs, proof_details = _safe_partial_proofs(v16, blockers)
            proof_details["canonical_prereq"] = details
            return proofs, proof_details
        return current()

    collect_proofs._nija_v61_precore_safe = True  # type: ignore[attr-defined]
    collect_proofs.__wrapped__ = current  # type: ignore[attr-defined]
    v16._collect_proofs = collect_proofs
    logger.critical(
        "FINAL_ACTIVATION_V61_PROOF_COLLECTION_PATCHED marker=%s pre_core_nonce_probe=false",
        MARKER,
    )
    return True


def _patch_v16_truth_sync() -> bool:
    """Make pre-live readiness equal current proof truth, not sticky history."""
    v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    current = getattr(v16, "_mark_proven_readiness", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v61_truth_sync", False):
        return True

    def mark_proven_readiness(proofs: dict[str, bool]) -> tuple[bool, list[str]]:
        table = importlib.import_module("bot.readiness_table")
        before = dict(table.snapshot())
        trading_state = _state_value()
        prelive = trading_state != "LIVE_ACTIVE"

        for key in _KEYS:
            if bool(proofs.get(key, False)):
                table.mark_ready(key)
            elif prelive:
                table.revoke_ready(key, reason="v61_current_proof_false")

        after = dict(table.snapshot())
        current_pending = [key for key in _KEYS if not bool(proofs.get(key, False))]
        table_pending = [key for key in _KEYS if not bool(after.get(key, False))]
        pending = [key for key in _KEYS if key in current_pending or key in table_pending]
        ready = not pending

        os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "1" if ready else "0"
        if prelive:
            authority = bool(proofs.get("authority_ready", False))
            nonce = bool(proofs.get("nonce_ready", False))
            os.environ["NIJA_AUTHORITY_READY"] = "1" if authority else "0"
            os.environ["NIJA_NONCE_READY"] = "1" if nonce else "0"
            os.environ["NIJA_RUNTIME_NONCE_READY"] = "1" if nonce else "0"

        logger.critical(
            "PREACTIVATION_READINESS_V61_TRUTH_SYNC marker=%s state=%s prelive=%s "
            "before=%s after=%s current_pending=%s table_pending=%s pending=%s",
            MARKER,
            trading_state,
            str(prelive).lower(),
            before,
            after,
            current_pending,
            table_pending,
            pending,
        )
        if ready:
            logger.critical(
                "PREACTIVATION_READY marker=%s authority_ready=true nonce_ready=true "
                "writer_authority=confirmed blockers_cleared=true current_proofs=true",
                MARKER,
            )
        return ready, pending

    mark_proven_readiness._nija_v61_truth_sync = True  # type: ignore[attr-defined]
    mark_proven_readiness.__wrapped__ = current  # type: ignore[attr-defined]
    v16._mark_proven_readiness = mark_proven_readiness
    logger.critical(
        "FINAL_ACTIVATION_V61_READINESS_TRUTH_PATCHED marker=%s false_proofs_revoke_pre_live=true",
        MARKER,
    )
    return True


def _activation_prerequisites() -> tuple[bool, list[str], dict[str, Any]]:
    ready, blockers, details = _canonical_core_bootstrap_status()
    halted, halt_reason = _seak_status()
    details["seak_halted"] = halted
    details["seak_reason"] = halt_reason
    if not ready:
        return False, blockers, details
    if halted:
        return False, [f"seak_halted:{halt_reason or 'unknown'}"], details

    try:
        v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
        proofs, proof_details = v16._collect_proofs()
    except Exception as exc:
        return False, [f"proof_collection_failed:{type(exc).__name__}:{exc}"], details

    details["proofs"] = proofs
    details["proof_details"] = proof_details
    proof_blockers = [key for key in _KEYS if not bool(proofs.get(key, False))]
    if proof_blockers:
        return False, [f"proof.{key}" for key in proof_blockers], details
    return True, [], details


def _log_activation_deferred(trigger: str, blockers: list[str], details: dict[str, Any]) -> None:
    logger.warning(
        "ACTIVATION_SINGLE_FLIGHT_DEFERRED marker=%s trigger=%s first_blocker=%s blockers=%s "
        "generation=%s core_registered=%s core_alive=%s bootstrap_state=%s seak_halted=%s "
        "seak_reason=%s nonce_probe_skipped=%s trading_fail_closed=true",
        MARKER,
        trigger,
        blockers[0] if blockers else "unknown",
        blockers,
        details.get("generation", 0),
        details.get("core_registered", False),
        details.get("core_alive", False),
        details.get("bootstrap_state", "unknown"),
        details.get("seak_halted", False),
        details.get("seak_reason", "") or "none",
        str(any(b.startswith(("core_", "bootstrap_state", "writer_epoch", "seak_halted")) for b in blockers)).lower(),
    )


def _patch_v60_request_activation() -> bool:
    """Guard every v60 request before a worker can be spawned."""
    v60 = importlib.import_module("bot.final_production_activation_repair_v60_patch")
    current = getattr(v60, "request_activation", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v61_prereq_guard", False):
        return True

    def request_activation(trigger: str) -> bool:
        ready, blockers, details = _activation_prerequisites()
        if not ready:
            _log_activation_deferred(str(trigger or "unspecified"), blockers, details)
            return False
        return bool(current(trigger))

    request_activation._nija_v61_prereq_guard = True  # type: ignore[attr-defined]
    request_activation.__wrapped__ = current  # type: ignore[attr-defined]
    v60.request_activation = request_activation
    logger.critical(
        "FINAL_ACTIVATION_V61_V60_REQUEST_PATCHED marker=%s canonical_prereqs_required=true",
        MARKER,
    )
    return True


def _patch_activation_commit_boundary() -> bool:
    """Protect the legacy activation monitor as well as the v60 worker."""
    monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
    current = getattr(monitor, "_commit_once", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v61_prereq_guard", False):
        return True

    def commit_once(sm: Any, meta: dict[str, Any]) -> bool:
        ready, blockers, details = _activation_prerequisites()
        if not ready:
            _log_activation_deferred("activation_commit_boundary", blockers, details)
            return False
        return bool(current(sm, meta))

    commit_once._nija_v61_prereq_guard = True  # type: ignore[attr-defined]
    commit_once.__wrapped__ = current  # type: ignore[attr-defined]
    monitor._commit_once = commit_once
    logger.critical(
        "FINAL_ACTIVATION_V61_COMMIT_BOUNDARY_PATCHED marker=%s pre_core_commit=false",
        MARKER,
    )
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        results = {
            "proof_collection": _patch_v16_proof_collection(),
            "readiness_truth": _patch_v16_truth_sync(),
            "v60_request": _patch_v60_request_activation(),
            "commit_boundary": _patch_activation_commit_boundary(),
        }
        ready = all(results.values())
        os.environ["NIJA_FINAL_PRODUCTION_ACTIVATION_V61_INSTALLED"] = "1" if ready else "0"
        _INSTALLED = ready
        logger.critical(
            "FINAL_PRODUCTION_ACTIVATION_V61_INSTALLED marker=%s ready=%s results=%s "
            "seak_mutation=false safety_thresholds_unchanged=true",
            MARKER,
            str(ready).lower(),
            results,
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_core_bootstrap_status",
    "_activation_prerequisites",
    "_safe_partial_proofs",
]
