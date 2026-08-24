"""Earliest kill-switch provenance protection (v217).

v213 correctly preserves an existing EMERGENCY_STOP marker once its monkey patch
is installed, but production proved the KillSwitch singleton can be constructed
before the later pre-core installer reaches v213.  The base constructor then calls
``_check_file_activation()``, which historically routed through
``_activate_internal('Kill switch file detected', 'FILE_SYSTEM')`` and rewrote the
existing marker with ``open(..., 'w')``.  That destroys the original Reason and
Activated evidence before the guarded recovery chain can classify the stop.

v217 is installed from the first live-startup sanitizer import, before normal
runtime modules are imported.  It only protects provenance and arms read-only
causal diagnostics.  It never clears an active stop, never grants authority,
never mutates risk/capital/nonce/position/order/fill truth, and never forces
LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_early_provenance_v217")
MARKER = "20260824-kill-switch-early-provenance-v217"
_FLAG = "NIJA_KILL_SWITCH_EARLY_PROVENANCE_V217_READY"
_PATCH_ATTR = "_nija_kill_switch_early_provenance_v217"
_LOCK = threading.RLock()
_INSTALLED = False


def _read_marker(path: object) -> dict[str, str]:
    marker_path = str(path or "").strip()
    if not marker_path or not os.path.exists(marker_path):
        return {"reason": "", "activated": "", "read_error": ""}
    try:
        with open(marker_path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(32_768)
    except Exception as exc:
        return {
            "reason": "",
            "activated": "",
            "read_error": f"{type(exc).__name__}:{exc}",
        }

    reason = ""
    activated = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not reason and line.startswith("Reason:"):
            reason = line.split(":", 1)[1].strip()
        elif not activated and line.startswith("Activated:"):
            activated = line.split(":", 1)[1].strip()
        if reason and activated:
            break
    return {"reason": reason, "activated": activated, "read_error": ""}


def _restart_reason(marker_reason: object) -> str:
    clean = str(marker_reason or "").replace("\r", " ").replace("\n", " ").strip()
    if not clean or clean == "Kill switch file detected":
        return "Kill switch file detected"
    return f"Kill switch file detected | persisted_reason={clean[:1024]}"


def _patch_class() -> bool:
    module = importlib.import_module("bot.kill_switch")
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False

    check = getattr(cls, "_check_file_activation", None)
    create = getattr(cls, "_create_kill_file", None)
    if not callable(check) or not callable(create):
        return False

    if not getattr(check, _PATCH_ATTR, False):
        @wraps(check)
        def check_file_activation_v217(self: Any) -> None:
            kill_file = str(getattr(self, "_kill_file", "") or "")
            if not kill_file or not os.path.exists(kill_file):
                return

            # If already active, preserve the marker and current causal record.
            if bool(getattr(self, "_is_active", False)):
                return

            meta = _read_marker(kill_file)
            record = {
                "reason": _restart_reason(meta.get("reason")),
                "source": "FILE_SYSTEM",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "restart_persistence": True,
                "persisted_marker_reason": str(meta.get("reason") or ""),
                "persisted_marker_activated": str(meta.get("activated") or ""),
                "marker_rewritten": False,
                "early_provenance_v217": True,
            }
            read_error = str(meta.get("read_error") or "")
            if read_error:
                record["persisted_marker_read_error"] = read_error

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
                "KILL_SWITCH_EARLY_V217_PRESERVED marker=%s source=FILE_SYSTEM "
                "persisted_reason=%s persisted_activated=%s read_error=%s "
                "marker_rewritten=false active_after=true recovery_eligibility_unchanged=true "
                "trading_fail_closed=true",
                MARKER,
                str(meta.get("reason") or "unavailable"),
                str(meta.get("activated") or "unavailable"),
                read_error or "none",
            )

        setattr(check_file_activation_v217, _PATCH_ATTR, True)
        setattr(check_file_activation_v217, "__wrapped__", check)
        cls._check_file_activation = check_file_activation_v217

    current_create = getattr(cls, "_create_kill_file", None)
    if callable(current_create) and not getattr(current_create, _PATCH_ATTR, False):
        @wraps(current_create)
        def create_kill_file_v217(self: Any, reason: str) -> Any:
            kill_file = str(getattr(self, "_kill_file", "") or "")
            if kill_file and os.path.exists(kill_file):
                meta = _read_marker(kill_file)
                LOGGER.critical(
                    "KILL_SWITCH_EARLY_V217_OVERWRITE_BLOCKED marker=%s path=%s "
                    "existing_reason=%s requested_reason=%s authoritative_marker_preserved=true "
                    "kill_switch_state_unchanged=true trading_fail_closed=true",
                    MARKER,
                    kill_file,
                    str(meta.get("reason") or "unavailable"),
                    str(reason or "unspecified"),
                )
                return None
            return current_create(self, reason)

        setattr(create_kill_file_v217, _PATCH_ATTR, True)
        setattr(create_kill_file_v217, "__wrapped__", current_create)
        cls._create_kill_file = create_kill_file_v217

    return True


def _arm_periodic_diagnostic() -> bool:
    try:
        module = importlib.import_module("bot.kill_switch_causal_diagnostic_v216_periodic_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        return callable(installer) and installer() is not False
    except Exception as exc:
        # Diagnostics are deliberately non-authoritative and must never become a
        # reason to open or close a trading gate.
        LOGGER.warning(
            "KILL_SWITCH_EARLY_V217_DIAGNOSTIC_DEFERRED marker=%s err=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            _arm_periodic_diagnostic()
            return True
        try:
            ok = _patch_class()
        except Exception as exc:
            LOGGER.critical(
                "KILL_SWITCH_EARLY_V217_INSTALL_FAILED marker=%s err=%s:%s "
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

    diag = _arm_periodic_diagnostic()
    LOGGER.critical(
        "KILL_SWITCH_EARLY_PROVENANCE_V217_READY marker=%s ready=true "
        "constructor_protected=true existing_marker_preserved=true "
        "marker_overwrite_blocked=true periodic_diagnostic_armed=%s "
        "direct_deactivate=false recovery_eligibility_unchanged=true "
        "execution_authority_unchanged=true forced_activation=false "
        "safety_gates_bypassed=false",
        MARKER,
        str(diag).lower(),
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_read_marker",
    "_restart_reason",
]
