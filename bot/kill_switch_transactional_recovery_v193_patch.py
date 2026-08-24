"""Repair restart-persisted kill-switch deactivation without weakening safety.

v193 addresses the production state where all canonical runtime proofs are healthy
but the process remains in EMERGENCY_STOP because a previously verified retired
heartbeat recovery was followed by another FILE_SYSTEM persistence record.

Two narrow repairs are applied:

1. KillSwitch.deactivate() becomes marker-first.  The EMERGENCY_STOP file must be
   removed successfully before the canonical deactivation is allowed to record a
   source-less deactivation boundary or move the FSM back to OFF.  If removal
   fails, the switch remains active and no deactivation record is created.
2. v143 provenance reconstruction may cross exactly one source-less boundary only
   when that boundary reason proves it was created by NIJA's existing verified
   retired-heartbeat recovery path.  It then reconstructs only the exact retired
   AUTHORITY_HEARTBEAT_EXPIRED/core_thread_dead origin.  Manual/UI/CLI/risk/unknown
   boundaries remain authoritative and fail closed.

v193 never calls KillSwitch.deactivate directly, never grants execution authority,
never forces LIVE_ACTIVE, and never changes risk, nonce, capital, position-sync,
or signal thresholds.  After installing the narrow provenance repair it delegates
one recheck to the existing v132/v140 guarded recovery path.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_transactional_recovery_v193")
MARKER = "20260823-kill-switch-transactional-recovery-v193"
_FLAG = "NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_READY"
_PATCH_ATTR = "_nija_kill_switch_transactional_recovery_v193"
_LOCK = threading.RLock()
_INSTALLED = False

_VERIFIED_RECOVERY_REASONS = {
    "v130 verified recovery from retired pre-v129 authority-heartbeat startup race",
    "verified recovery from retired authority-heartbeat/core-death restart persistence",
}


def _restart_persistence_record(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    source = str(item.get("source") or "").strip().upper()
    reason = str(item.get("reason") or "")
    return source == "FILE_SYSTEM" and "Kill switch file detected" in reason


def _retired_heartbeat_reason(reason: object) -> bool:
    text = str(reason or "").strip().upper()
    heartbeat = "AUTHORITY_HEARTBEAT_EXPIRED" in text or "AUTHORITY HEARTBEAT EXPIRED" in text
    dead_core = "CORE_THREAD_DEAD" in text or "NIJA_CORE_THREAD_ALIVE" in text
    return bool(heartbeat and dead_core)


def _verified_recovery_boundary(reason: object) -> bool:
    return str(reason or "").strip().lower() in _VERIFIED_RECOVERY_REASONS


def _derive_persisted_cause_v193(history: object) -> dict[str, Any] | None:
    """Reconstruct only the retired-heartbeat origin across a verified recovery boundary."""
    if not isinstance(history, list) or not history:
        return None
    if not _restart_persistence_record(history[-1]):
        return None

    skipped = 0
    crossed_verified_boundary = False
    boundary_reason = ""

    for item in reversed(history[:-1]):
        if not isinstance(item, dict):
            return {
                "blocked": "malformed_history_boundary",
                "persistence_records_skipped": skipped,
            }

        source = str(item.get("source") or "").strip()
        reason = str(item.get("reason") or "")

        if _restart_persistence_record(item):
            skipped += 1
            continue

        if not source:
            if not crossed_verified_boundary and _verified_recovery_boundary(reason):
                crossed_verified_boundary = True
                boundary_reason = reason
                continue
            return {
                "blocked": "deactivation_boundary",
                "boundary_reason": reason,
                "persistence_records_skipped": skipped,
            }

        if crossed_verified_boundary:
            if not _retired_heartbeat_reason(reason):
                return {
                    "blocked": "verified_recovery_origin_not_retired_heartbeat",
                    "boundary_reason": boundary_reason,
                    "origin_source": source,
                    "origin_reason": reason,
                    "persistence_records_skipped": skipped,
                }
            if source.strip().upper() in {"UI", "CLI", "FILE_SYSTEM"}:
                return {
                    "blocked": "verified_recovery_origin_source_forbidden",
                    "boundary_reason": boundary_reason,
                    "origin_source": source,
                    "persistence_records_skipped": skipped,
                }
            return {
                "source": source,
                "reason": reason,
                "persistence_records_skipped": skipped,
                "verified_recovery_boundary_crossed": True,
                "boundary_reason": boundary_reason,
            }

        return {
            "source": source,
            "reason": reason,
            "persistence_records_skipped": skipped,
        }

    return {
        "blocked": "origin_unavailable",
        "boundary_reason": boundary_reason,
        "persistence_records_skipped": skipped,
    }


def _patch_transactional_deactivate() -> bool:
    kill_module = importlib.import_module("bot.kill_switch")
    cls = getattr(kill_module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "deactivate", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def deactivate_v193(self: Any, reason: str = "Manual deactivation") -> Any:
        # Do not create a deactivation boundary until the authoritative file
        # marker has actually disappeared.
        kill_file = str(getattr(self, "_kill_file", "") or "")
        active = bool(getattr(self, "_is_active", False))
        if active and kill_file and os.path.exists(kill_file):
            try:
                os.remove(kill_file)
            except Exception as exc:
                LOGGER.critical(
                    "KILL_SWITCH_V193_DEACTIVATION_REFUSED marker=%s stage=marker_remove "
                    "err=%s:%s active_preserved=true deactivation_record_created=false "
                    "trading_fail_closed=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
                return False
            if os.path.exists(kill_file):
                LOGGER.critical(
                    "KILL_SWITCH_V193_DEACTIVATION_REFUSED marker=%s stage=marker_verify "
                    "marker_still_exists=true active_preserved=true deactivation_record_created=false "
                    "trading_fail_closed=true",
                    MARKER,
                )
                return False

        result = current(self, reason)

        # A marker recreated concurrently is an authoritative new stop. Restore
        # canonical active state through the existing activation API; never force
        # execution or silently accept an inconsistent inactive/file-present pair.
        if kill_file and os.path.exists(kill_file) and not bool(getattr(self, "_is_active", False)):
            LOGGER.critical(
                "KILL_SWITCH_V193_MARKER_REAPPEARED marker=%s after_deactivate=true "
                "reactivate_file_stop=true trading_fail_closed=true",
                MARKER,
            )
            try:
                self.activate("Kill switch file detected after deactivation", "FILE_SYSTEM")
            except Exception as exc:
                LOGGER.critical(
                    "KILL_SWITCH_V193_REACTIVATION_FAILED marker=%s err=%s:%s "
                    "trading_fail_closed=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
            return False
        return result

    setattr(deactivate_v193, _PATCH_ATTR, True)
    setattr(deactivate_v193, "__wrapped__", current)
    cls.deactivate = deactivate_v193
    return True


def _patch_v143_provenance() -> bool:
    v143 = importlib.import_module("bot.kill_switch_persistence_provenance_v143_patch")
    original = getattr(v143, "_derive_persisted_cause", None)
    if not callable(original):
        return False

    if not getattr(original, _PATCH_ATTR, False):
        @wraps(original)
        def derive_v193(history: object) -> dict[str, Any] | None:
            enhanced = _derive_persisted_cause_v193(history)
            if isinstance(enhanced, dict) and enhanced.get("verified_recovery_boundary_crossed"):
                LOGGER.critical(
                    "KILL_SWITCH_V193_VERIFIED_BOUNDARY_RECONSTRUCTED marker=%s "
                    "causal_source=%s persistence_records_skipped=%s "
                    "delegated_recovery=true generic_auto_clear=false",
                    MARKER,
                    enhanced.get("source") or "unknown",
                    enhanced.get("persistence_records_skipped", 0),
                )
                return enhanced
            # Preserve v143's existing policy for all ordinary histories.  The
            # enhanced result is used only to retain richer blocked diagnostics.
            base = original(history)
            return enhanced if isinstance(enhanced, dict) and enhanced.get("blocked") else base

        setattr(derive_v193, _PATCH_ATTR, True)
        setattr(derive_v193, "__wrapped__", original)
        v143._derive_persisted_cause = derive_v193

    # Reassert v143's status and causal-reader wrappers, then let its existing
    # v186 post-reassert path delegate recovery to v132/v140.
    installer = getattr(v143, "install_import_hook", None) or getattr(v143, "install", None)
    return callable(installer) and installer() is not False


def _patch_release_manifest() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["kill_switch_transactional_recovery_v193"] = _FLAG
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            ok = bool(
                _patch_transactional_deactivate()
                and _patch_release_manifest()
            )
            if not ok:
                os.environ.pop(_FLAG, None)
                return False

            # Publish readiness before replaying v143 because the release audit
            # may observe the newly registered flag during that replay.
            os.environ[_FLAG] = "1"
            if not _patch_v143_provenance():
                os.environ.pop(_FLAG, None)
                return False
            first = not _INSTALLED
            _INSTALLED = True
        except Exception as exc:
            os.environ.pop(_FLAG, None)
            LOGGER.critical(
                "KILL_SWITCH_V193_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False

    if first:
        LOGGER.critical(
            "KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_INSTALLED marker=%s "
            "marker_first_deactivation=true verified_heartbeat_boundary_only=true "
            "manual_ui_cli_risk_boundaries_preserved=true direct_deactivate=false "
            "execution_authority_unchanged=true forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_derive_persisted_cause_v193",
    "_retired_heartbeat_reason",
    "_verified_recovery_boundary",
]
