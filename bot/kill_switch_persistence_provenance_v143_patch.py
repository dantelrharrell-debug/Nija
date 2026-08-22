"""Preserve kill-switch activation provenance across repeated restart persistence.

Production 2026-08-18 showed an otherwise healthy runtime remaining in
``EMERGENCY_STOP`` with only ``authority_ready``/``execution_ready`` false.
The canonical KillSwitch exposes only ``recent_history[-5:]``. Every restart
while ``EMERGENCY_STOP`` exists appends another ``FILE_SYSTEM / Kill switch file
detected`` record, so the original activation can age out of that five-record
window. v140 then cannot prove that a persisted stop came from the retired
authority-heartbeat/core-death race and correctly refuses recovery.

v143 repairs provenance only; it does not clear a kill switch itself:

* derive one compact persisted-stop causal record from the KillSwitch's full
  in-memory history while keeping the public ``recent_history`` window intact;
* traverse any number of consecutive restart-persistence records;
* treat every source-less deactivation record as a hard provenance boundary;
* feed the bounded causal record to v140, v131, and v130 so their existing
  narrow heartbeat-only recovery policy can make the decision;
* preserve manual/UI/CLI, unrelated automatic risk, unknown-source, direct new
  heartbeat, and post-deactivation file stops fail-closed.

v185 hardens v143's idempotence after production installer replay. A replay can
replace ``KillSwitch.get_status`` or one of the causal-reader function objects
without clearing v143's process-local installed flag. v143 now reasserts its
status wrapper, causal-reader anchors, and release-manifest contract on every
installer invocation instead of returning early solely because the flag is set.

No live state, execution authority, risk gate, nonce, writer lease, SEAK state,
capital freshness, or publication expiry is changed by this patch.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_persistence_provenance_v143")
MARKER = "20260818-kill-switch-persistence-provenance-v143"
REASSERT_MARKER = "20260822-kill-switch-provenance-reassert-v185"
RELEASE_ID = "20260818-runtime-convergence-v143"
_FLAG = "NIJA_KILL_SWITCH_PERSISTENCE_PROVENANCE_V143_READY"
_REASSERT_FLAG = "NIJA_KILL_SWITCH_PROVENANCE_REASSERT_V185_READY"
_PATCH_ATTR = "_nija_kill_switch_persistence_provenance_v143"
_META_KEY = "_nija_persisted_cause_v143"
_DEPTH_KEY = "_nija_persistence_history_depth_v143"
_LOCK = threading.RLock()
_INSTALLED = False
_LAST_PROVENANCE_SIGNATURE = ""


def _restart_persistence_record(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    source = str(item.get("source") or "").strip().upper()
    reason = str(item.get("reason") or "")
    return source == "FILE_SYSTEM" and "Kill switch file detected" in reason


def _derive_persisted_cause(history: object) -> dict[str, Any] | None:
    """Return one bounded causal record for the current restart-persisted stop.

    A source-less record is written by ``KillSwitch.deactivate`` and therefore
    terminates provenance. Crossing that boundary could misattribute a later
    manually-created ``EMERGENCY_STOP`` file to an older automatic heartbeat
    activation, so v143 deliberately refuses to scan past it.
    """
    if not isinstance(history, list) or not history:
        return None
    latest = history[-1]
    if not _restart_persistence_record(latest):
        return None

    skipped = 0
    for item in reversed(history[:-1]):
        if not isinstance(item, dict):
            return {
                "blocked": "malformed_history_boundary",
                "persistence_records_skipped": skipped,
            }

        source = str(item.get("source") or "").strip()
        reason = str(item.get("reason") or "")

        if not source:
            return {
                "blocked": "deactivation_boundary",
                "persistence_records_skipped": skipped,
            }

        if _restart_persistence_record(item):
            skipped += 1
            continue

        return {
            "source": source,
            "reason": reason,
            "persistence_records_skipped": skipped,
        }

    return {
        "blocked": "origin_unavailable",
        "persistence_records_skipped": skipped,
    }


def _announce_provenance(meta: dict[str, Any], depth: int) -> None:
    global _LAST_PROVENANCE_SIGNATURE
    blocked = str(meta.get("blocked") or "")
    source = str(meta.get("source") or "")
    reason = str(meta.get("reason") or "")
    skipped = int(meta.get("persistence_records_skipped") or 0)
    signature = f"{blocked}|{source}|{reason}|{skipped}|{depth}"
    with _LOCK:
        if signature == _LAST_PROVENANCE_SIGNATURE:
            return
        _LAST_PROVENANCE_SIGNATURE = signature

    if blocked:
        LOGGER.critical(
            "KILL_SWITCH_PROVENANCE_V143_PRESERVED marker=%s block=%s history_depth=%d "
            "persistence_records_skipped=%d auto_clear=false trading_fail_closed=true",
            MARKER,
            blocked,
            depth,
            skipped,
        )
    else:
        LOGGER.critical(
            "KILL_SWITCH_PROVENANCE_V143_RECONSTRUCTED marker=%s history_depth=%d "
            "persistence_records_skipped=%d causal_source=%s causal_reason=%s "
            "recovery_decision_delegated=true generic_auto_clear=false",
            MARKER,
            depth,
            skipped,
            source or "unknown",
            reason or "unknown",
        )


def _patch_kill_switch_status() -> bool:
    module = importlib.import_module("bot.kill_switch")
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "get_status", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def get_status_v143(self: Any) -> dict[str, Any]:
        raw = current(self)
        status = dict(raw or {}) if isinstance(raw, dict) else {}
        try:
            lock = getattr(self, "_lock", None)
            if lock is not None:
                with lock:
                    history = list(getattr(self, "_activation_history", []) or [])
            else:
                history = list(getattr(self, "_activation_history", []) or [])
        except Exception as exc:
            LOGGER.warning(
                "KILL_SWITCH_PROVENANCE_V143_HISTORY_PROBE_FAILED marker=%s err=%s:%s "
                "existing_status_preserved=true trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return status

        meta = _derive_persisted_cause(history)
        if meta is not None:
            status[_META_KEY] = dict(meta)
            status[_DEPTH_KEY] = len(history)
            _announce_provenance(meta, len(history))
        return status

    setattr(get_status_v143, _PATCH_ATTR, True)
    setattr(get_status_v143, "_nija_v143_original", current)
    cls.get_status = get_status_v143
    return True


def _causal_activation_from_status(
    status: dict[str, Any],
    fallback: Any = None,
) -> tuple[str, str]:
    history = list(status.get("recent_history") or [])
    latest = history[-1] if history and isinstance(history[-1], dict) else {}
    if _restart_persistence_record(latest):
        meta = status.get(_META_KEY)
        if isinstance(meta, dict):
            blocked = str(meta.get("blocked") or "").strip()
            if blocked:
                return f"v143_provenance_blocked:{blocked}", "PROVENANCE_BOUNDARY"
            source = str(meta.get("source") or "").strip()
            reason = str(meta.get("reason") or "")
            if source:
                return reason, source

    if callable(fallback):
        try:
            result = fallback(status)
            if isinstance(result, tuple) and len(result) >= 2:
                return str(result[0] or ""), str(result[1] or "")
        except Exception:
            pass

    if not history:
        return "", ""
    return str(latest.get("reason") or ""), str(latest.get("source") or "")


def _wrap_causal_reader(current: Any, fallback_attr: str) -> Any:
    if getattr(current, _PATCH_ATTR, False):
        return current

    @wraps(current)
    def causal_activation_v143(status: dict[str, Any]) -> tuple[str, str]:
        return _causal_activation_from_status(status, current)

    setattr(causal_activation_v143, _PATCH_ATTR, True)
    setattr(causal_activation_v143, fallback_attr, current)
    return causal_activation_v143


def _patch_causal_readers() -> bool:
    v140 = importlib.import_module("bot.runtime_killswitch_authority_liveness_patch")
    v131 = importlib.import_module("bot.readiness_killswitch_causality_v131_patch")
    v130 = importlib.import_module("bot.kill_switch_stale_heartbeat_recovery_v130_patch")

    current_v140 = getattr(v140, "_causal_activation", None)
    current_v131 = getattr(v131, "_causal_activation", None)
    if not callable(current_v140) or not callable(current_v131):
        return False

    anchored_v140 = _wrap_causal_reader(current_v140, "_nija_v143_v140_fallback")
    anchored_v131 = _wrap_causal_reader(current_v131, "_nija_v143_v131_fallback")
    v140._causal_activation = anchored_v140
    v131._causal_activation = anchored_v131

    # v130 captured v131's old function object during its installer. Always
    # re-anchor that compatibility pointer so installer replay cannot leave it
    # reading a stale bounded-history implementation while v143 reports ready.
    v130._latest_activation = anchored_v131
    return True


def _patch_release_manifest() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict) or not isinstance(installers, tuple):
        return False

    required["kill_switch_persistence_provenance_v143"] = _FLAG
    required["kill_switch_provenance_reassert_v185"] = _REASSERT_FLAG
    own = ("bot.kill_switch_persistence_provenance_v143_patch", "install_import_hook")
    if own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)

    manifest.DECLARED_RELEASE_ID = RELEASE_ID
    manifest.RELEASE_ID = RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        # v143 is a follow-on to the existing narrow v140 recovery and the v142
        # runtime release. Refuse partial installation rather than widening any
        # recovery path in an unknown runtime composition.
        if os.environ.get("NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY") != "1":
            os.environ.pop(_FLAG, None)
            os.environ.pop(_REASSERT_FLAG, None)
            return False
        if os.environ.get("NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY") != "1":
            os.environ.pop(_FLAG, None)
            os.environ.pop(_REASSERT_FLAG, None)
            return False

        # Do not return early merely because process-local installation state is
        # already true. Release verification can replay installers after imports
        # or compatibility layers replace function/class objects. Reassert each
        # non-authoritative wrapper every time so "ready" means currently owned.
        was_installed = bool(_INSTALLED and os.environ.get(_FLAG) == "1")
        try:
            ok = bool(
                _patch_kill_switch_status()
                and _patch_causal_readers()
                and _patch_release_manifest()
            )
        except Exception as exc:
            LOGGER.critical(
                "KILL_SWITCH_PROVENANCE_V143_INSTALL_FAILED marker=%s err=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ok = False

        if not ok:
            os.environ.pop(_FLAG, None)
            os.environ.pop(_REASSERT_FLAG, None)
            os.environ["NIJA_RUNTIME_RELEASE_READY"] = "0"
            return False

        os.environ[_FLAG] = "1"
        os.environ[_REASSERT_FLAG] = "1"
        first = not _INSTALLED
        _INSTALLED = True

    if first:
        LOGGER.critical(
            "KILL_SWITCH_PROVENANCE_V143_INSTALLED marker=%s release=%s "
            "repeated_restart_provenance=true deactivation_boundary_authoritative=true "
            "manual_ui_cli_stops_preserved=true risk_stops_preserved=true "
            "direct_new_stops_preserved=true generic_auto_clear=false "
            "execution_authority_unchanged=true risk_gates_unchanged=true force_live=false",
            MARKER,
            RELEASE_ID,
        )
    elif was_installed:
        LOGGER.critical(
            "KILL_SWITCH_PROVENANCE_V185_REASSERTED marker=%s "
            "kill_switch_status_owner=true causal_readers_reanchored=true "
            "v130_pointer_reanchored=true generic_auto_clear=false "
            "manual_ui_cli_stops_preserved=true risk_stops_preserved=true "
            "execution_authority_unchanged=true force_live=false",
            REASSERT_MARKER,
        )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "REASSERT_MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_derive_persisted_cause",
    "_causal_activation_from_status",
    "_patch_kill_switch_status",
    "_patch_causal_readers",
    "_patch_release_manifest",
]
