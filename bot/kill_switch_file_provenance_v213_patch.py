"""Preserve the original EMERGENCY_STOP marker provenance across restarts (v213).

Production 2026-08-24 proved the execution pipeline could reach ECEL and the
pre-dispatch gate while the canonical kill switch remained active, but the
runtime could only classify the stop as ``other_preserved``.  The base
``KillSwitch._check_file_activation`` re-activates an existing marker by calling
``_activate_internal('Kill switch file detected', 'FILE_SYSTEM')``.  That helper
then calls ``_create_kill_file`` and rewrites the already-existing marker,
permanently replacing the original ``Reason:``/``Activated:`` evidence.

v213 repairs provenance only.  It never clears an active stop, never grants
execution authority, never forces LIVE_ACTIVE, and never changes risk, nonce,
capital, position-sync, ECEL, order, or fill gates.

The repair:
* detects an existing EMERGENCY_STOP marker without rewriting it;
* records a normal FILE_SYSTEM restart-persistence history entry so the existing
  v132/v143/v193 guarded recovery chain keeps its exact eligibility semantics;
* carries the marker's original Reason/Activated text as diagnostic metadata;
* refuses to overwrite any already-existing stop marker from later activation
  paths, preserving the earliest on-disk evidence;
* publishes a release-manifest readiness flag and structured diagnostics.

Importantly, marker text alone is never treated as sufficient recovery proof.
Manual/UI/CLI/risk/unknown stops remain fail-closed, and v213 never calls
``KillSwitch.deactivate``.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_file_provenance_v213")
MARKER = "20260824-kill-switch-file-provenance-v213"
_FLAG = "NIJA_KILL_SWITCH_FILE_PROVENANCE_V213_READY"
_PATCH_ATTR = "_nija_kill_switch_file_provenance_v213"
_LOCK = threading.RLock()
_INSTALLED = False


def _read_marker_metadata(path: object) -> dict[str, str]:
    marker_path = str(path or "").strip()
    if not marker_path or not os.path.exists(marker_path):
        return {"reason": "", "activated": "", "read_error": ""}

    try:
        with open(marker_path, "r", encoding="utf-8", errors="replace") as handle:
            # The marker is intentionally tiny. Bound the read anyway so a
            # malformed/operator-created file cannot create an unbounded probe.
            text = handle.read(32_768)
    except Exception as exc:
        return {
            "reason": "",
            "activated": "",
            "read_error": f"{type(exc).__name__}:{exc}",
        }

    reason = ""
    activated = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not reason and line.startswith("Reason:"):
            reason = line.split(":", 1)[1].strip()
        elif not activated and line.startswith("Activated:"):
            activated = line.split(":", 1)[1].strip()
        if reason and activated:
            break
    return {"reason": reason, "activated": activated, "read_error": ""}


def _restart_reason(marker_reason: str) -> str:
    # Keep the legacy phrase so v132/v143 continue to recognize this as a
    # restart-persistence record.  The preserved marker reason is diagnostic
    # evidence only; it does not widen recovery eligibility.
    clean = str(marker_reason or "").strip().replace("\n", " ")
    if not clean or clean == "Kill switch file detected":
        return "Kill switch file detected"
    return f"Kill switch file detected | persisted_reason={clean[:1024]}"


def _patch_file_activation() -> bool:
    module = importlib.import_module("bot.kill_switch")
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_check_file_activation", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def check_file_activation_v213(self: Any) -> None:
        kill_file = str(getattr(self, "_kill_file", "") or "")
        if not kill_file or not os.path.exists(kill_file):
            return

        LOGGER.warning(
            "KILL_SWITCH_FILE_V213_DETECTED marker=%s path=%s active_before=%s",
            MARKER,
            kill_file,
            bool(getattr(self, "_is_active", False)),
        )
        if bool(getattr(self, "_is_active", False)):
            return

        meta = _read_marker_metadata(kill_file)
        marker_reason = str(meta.get("reason") or "")
        marker_activated = str(meta.get("activated") or "")
        read_error = str(meta.get("read_error") or "")
        record = {
            "reason": _restart_reason(marker_reason),
            "source": "FILE_SYSTEM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "restart_persistence": True,
            "persisted_marker_reason": marker_reason,
            "persisted_marker_activated": marker_activated,
            "marker_rewritten": False,
        }
        if read_error:
            record["persisted_marker_read_error"] = read_error

        # Preserve the exact base-class state semantics, except do not route
        # through _activate_internal because that helper recreates/truncates the
        # marker.  Persisting the in-memory active bit + history is sufficient;
        # the existing file remains the authoritative hard-stop signal.
        self._is_active = True
        history = getattr(self, "_activation_history", None)
        if not isinstance(history, list):
            history = []
            self._activation_history = history
        history.append(record)

        persist = getattr(self, "_persist_state", None)
        if callable(persist):
            persist()

        LOGGER.critical(
            "KILL_SWITCH_FILE_V213_PRESERVED marker=%s source=FILE_SYSTEM "
            "persisted_reason=%s persisted_activated=%s read_error=%s "
            "marker_rewritten=false active_after=true recovery_eligibility_unchanged=true "
            "generic_auto_clear=false trading_fail_closed=true",
            MARKER,
            marker_reason or "unavailable",
            marker_activated or "unavailable",
            read_error or "none",
        )

    setattr(check_file_activation_v213, _PATCH_ATTR, True)
    setattr(check_file_activation_v213, "__wrapped__", current)
    cls._check_file_activation = check_file_activation_v213
    return True


def _patch_marker_creation() -> bool:
    module = importlib.import_module("bot.kill_switch")
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_create_kill_file", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def create_kill_file_v213(self: Any, reason: str) -> Any:
        kill_file = str(getattr(self, "_kill_file", "") or "")
        if kill_file and os.path.exists(kill_file):
            meta = _read_marker_metadata(kill_file)
            LOGGER.critical(
                "KILL_SWITCH_FILE_V213_OVERWRITE_BLOCKED marker=%s path=%s "
                "existing_reason=%s requested_reason=%s authoritative_marker_preserved=true "
                "kill_switch_state_unchanged=true trading_fail_closed=true",
                MARKER,
                kill_file,
                str(meta.get("reason") or "unavailable"),
                str(reason or "unspecified"),
            )
            return None
        return current(self, reason)

    setattr(create_kill_file_v213, _PATCH_ATTR, True)
    setattr(create_kill_file_v213, "__wrapped__", current)
    cls._create_kill_file = create_kill_file_v213
    return True


def _patch_release_manifest() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict) or not isinstance(installers, tuple):
        return False

    required["kill_switch_file_provenance_v213"] = _FLAG
    own = ("bot.kill_switch_file_provenance_v213_patch", "install_import_hook")
    if own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            ok = bool(
                _patch_file_activation()
                and _patch_marker_creation()
                and _patch_release_manifest()
            )
        except Exception as exc:
            LOGGER.critical(
                "KILL_SWITCH_FILE_V213_INSTALL_FAILED marker=%s err=%s:%s "
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
        first = not _INSTALLED
        _INSTALLED = True

    if first:
        LOGGER.critical(
            "KILL_SWITCH_FILE_PROVENANCE_V213_READY marker=%s ready=true "
            "existing_marker_preserved=true original_reason_preserved=true "
            "restart_record_compatible=true marker_text_not_recovery_proof=true "
            "direct_deactivate=false execution_authority_unchanged=true "
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
    "_read_marker_metadata",
    "_restart_reason",
]
