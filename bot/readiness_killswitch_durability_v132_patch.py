"""Make current-proof readiness and stale-stop causality durable at runtime.

v132 addresses two observed post-startup regressions without weakening safety:
1) later compatibility churn can replay v58's exported incremental readiness
   publisher, reintroducing sticky True readiness despite false current proofs;
2) the v130 stale-stop worker is startup-bounded, so a persisted restart-file
   record can re-surface the retired v128 heartbeat stop long after boot.

This patch never clears manual/UI/CLI stops, never clears a direct new heartbeat
activation, never changes SEAK, nonce, risk, or execution authority, and never
forces LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Any

LOGGER = logging.getLogger("nija.readiness_killswitch_durability_v132")
MARKER = "20260817-readiness-killswitch-durability-v132"
RELEASE_ID = "20260817-runtime-convergence-v132"
_FLAG = "NIJA_READINESS_KILLSWITCH_DURABILITY_V132_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False
_KEYS = (
    "broker_connected", "balance_hydrated", "authority_ready", "capital_ready",
    "risk_ready", "strategy_ready", "execution_ready", "nonce_ready", "bootstrap_ready",
)


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


def _durable_truth_sync(proofs: dict[str, bool]) -> tuple[bool, list[str]]:
    table = importlib.import_module("bot.readiness_table")
    before = dict(table.snapshot())
    state = _state_value()
    prelive = state != "LIVE_ACTIVE"

    for key in _KEYS:
        if bool(proofs.get(key, False)):
            table.mark_ready(key)
        elif prelive:
            table.revoke_ready(key, reason="v132_current_proof_false")

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

    LOGGER.critical(
        "PREACTIVATION_READINESS_V132_TRUTH_SYNC marker=%s state=%s prelive=%s "
        "before=%s after=%s current_pending=%s table_pending=%s pending=%s",
        MARKER, state, str(prelive).lower(), before, after, current_pending, table_pending, pending,
    )
    return ready, pending


_durable_truth_sync._nija_v61_truth_sync = True  # type: ignore[attr-defined]
_durable_truth_sync._nija_v132_truth_sync = True  # type: ignore[attr-defined]


def _anchor_readiness_owner() -> bool:
    v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    v58 = importlib.import_module("bot.final_production_activation_repair_v58_patch")

    # Replace the exported v58 callable itself. If any later installer assigns
    # v16._mark_proven_readiness = v58._incremental_mark_proven_readiness, it
    # still lands on current-proof truth synchronization rather than sticky True.
    v58._incremental_mark_proven_readiness = _durable_truth_sync
    v16._mark_proven_readiness = _durable_truth_sync

    original_patch = getattr(v58, "_patch_readiness", None)
    if callable(original_patch) and not getattr(original_patch, "_nija_v132_owner", False):
        def patch_readiness_v132() -> bool:
            v58._incremental_mark_proven_readiness = _durable_truth_sync
            v16._mark_proven_readiness = _durable_truth_sync
            LOGGER.critical(
                "READINESS_V132_OWNER_REASSERTED marker=%s source=v58_patch_readiness current_proof_sync=true",
                MARKER,
            )
            return True
        patch_readiness_v132._nija_v132_owner = True  # type: ignore[attr-defined]
        v58._patch_readiness = patch_readiness_v132

    LOGGER.critical(
        "READINESS_V132_OWNER_ANCHORED marker=%s v58_export_replaced=true v16_owner=true synthetic_readiness=false",
        MARKER,
    )
    return True


def _raw_latest_history(status: dict[str, Any]) -> tuple[str, str]:
    history = list(status.get("recent_history") or [])
    if not history or not isinstance(history[-1], dict):
        return "", ""
    latest = history[-1]
    return str(latest.get("reason") or ""), str(latest.get("source") or "")


def _eligible_persisted_retired_stop(status: dict[str, Any]) -> tuple[bool, str]:
    latest_reason, latest_source = _raw_latest_history(status)
    if latest_source.strip().upper() != "FILE_SYSTEM" or "Kill switch file detected" not in latest_reason:
        return False, "latest_not_restart_persistence"

    try:
        from bot.readiness_killswitch_causality_v131_patch import _causal_activation
        reason, source = _causal_activation(status)
    except Exception as exc:
        return False, f"causal_probe:{type(exc).__name__}"

    source_u = str(source or "").strip().upper()
    if source_u in {"MANUAL", "UI", "CLI", "FILE_SYSTEM"}:
        return False, "causal_source_forbidden"
    if "AUTHORITY_HEARTBEAT_EXPIRED" not in reason or "core_thread_dead" not in reason:
        return False, "causal_reason_not_retired_heartbeat"
    return True, reason


def _attempt_persisted_stop_recovery() -> bool:
    from bot.kill_switch import get_kill_switch
    ks = get_kill_switch()
    status = ks.get_status()
    if not bool(status.get("is_active")):
        return False

    eligible, detail = _eligible_persisted_retired_stop(status)
    if not eligible:
        LOGGER.critical(
            "KILL_SWITCH_V132_PRESERVED marker=%s detail=%s direct_new_stops_never_auto_clear=true",
            MARKER, detail,
        )
        return False

    try:
        from bot import kill_switch_stale_heartbeat_recovery_v130_patch as v130
        healthy, health_detail = v130._runtime_proofs_healthy()
        if not healthy:
            LOGGER.warning(
                "KILL_SWITCH_V132_RECOVERY_DEFERRED marker=%s detail=%s trading_fail_closed=true",
                MARKER, health_detail,
            )
            return False
        recovered = bool(v130._attempt_recovery())
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_V132_RECOVERY_FAILED marker=%s err=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False

    if recovered:
        LOGGER.critical(
            "KILL_SWITCH_V132_PERSISTED_STALE_STOP_RECOVERED marker=%s "
            "latest_record=restart_persistence causal_reason=%s canonical_activation_required=true",
            MARKER, detail,
        )
    return recovered


def _durability_worker() -> None:
    last_owner_check = 0.0
    while True:
        try:
            now = time.monotonic()
            if now - last_owner_check >= 5.0:
                v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
                current = getattr(v16, "_mark_proven_readiness", None)
                if not getattr(current, "_nija_v132_truth_sync", False):
                    _anchor_readiness_owner()
                    LOGGER.critical(
                        "READINESS_V132_OWNER_DRIFT_REPAIRED marker=%s fail_closed=true",
                        MARKER,
                    )
                last_owner_check = now
            _attempt_persisted_stop_recovery()
        except Exception as exc:
            LOGGER.warning(
                "V132_DURABILITY_MONITOR_ERROR marker=%s err=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        time.sleep(5.0)


def _patch_release_manifest() -> bool:
    from bot import runtime_release_manifest_patch as manifest
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["readiness_killswitch_durability_v132"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        try:
            ok = _anchor_readiness_owner() and _patch_release_manifest()
        except Exception as exc:
            LOGGER.critical(
                "READINESS_KILLSWITCH_DURABILITY_V132_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc, exc_info=True,
            )
            ok = False
        if not ok:
            os.environ.pop(_FLAG, None)
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
        threading.Thread(
            target=_durability_worker,
            name="ReadinessKillSwitchDurabilityV132",
            daemon=True,
        ).start()
        LOGGER.critical(
            "READINESS_KILLSWITCH_DURABILITY_V132_INSTALLED marker=%s release=%s "
            "generic_auto_clear=false direct_new_heartbeat_stops_preserved=true manual_stops_preserved=true "
            "risk_gates_unchanged=true seak_unchanged=true execution_authority_unchanged=true",
            MARKER, RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "_durable_truth_sync",
    "_eligible_persisted_retired_stop", "_anchor_readiness_owner",
]
