"""Bounded kill-switch causal diagnostics (v215).

This module exists only to make a preserved production stop explainable.  It
reads the canonical KillSwitch status, the v143/v193 causal reader (when
available), and the preserved EMERGENCY_STOP marker metadata from v213, then
emits one bounded structured diagnostic.

It never calls activate/deactivate, never removes or rewrites the marker, never
changes the state machine, readiness, execution authority, nonce, capital,
position sync, risk, ECEL, order or fill gates, and never forces LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_causal_diagnostic_v215")
MARKER = "20260824-kill-switch-causal-diagnostic-v215"
_FLAG = "NIJA_KILL_SWITCH_CAUSAL_DIAGNOSTIC_V215_READY"
_LOCK = threading.RLock()
_LAST_SIGNATURE = ""


def _bounded(value: object, limit: int = 512) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[: max(1, int(limit))] or "unavailable"


def _status() -> tuple[Any, dict[str, Any]]:
    module = importlib.import_module("bot.kill_switch")
    getter = getattr(module, "get_kill_switch", None)
    ks = getter() if callable(getter) else None
    status = ks.get_status() if ks is not None and callable(getattr(ks, "get_status", None)) else {}
    return ks, dict(status or {}) if isinstance(status, dict) else {}


def _causal(status: dict[str, Any]) -> tuple[str, str]:
    try:
        v140 = importlib.import_module("bot.runtime_killswitch_authority_liveness_patch")
        reader = getattr(v140, "_causal_activation", None)
        if callable(reader):
            result = reader(status)
            if isinstance(result, tuple) and len(result) >= 2:
                return str(result[0] or ""), str(result[1] or "")
    except Exception:
        pass
    history = list(status.get("recent_history") or [])
    latest = history[-1] if history and isinstance(history[-1], dict) else {}
    return str(latest.get("reason") or ""), str(latest.get("source") or "")


def _marker_meta(ks: Any) -> dict[str, str]:
    try:
        v213 = importlib.import_module("bot.kill_switch_file_provenance_v213_patch")
        reader = getattr(v213, "_read_marker_metadata", None)
        if callable(reader):
            result = reader(getattr(ks, "_kill_file", ""))
            if isinstance(result, dict):
                return {str(k): str(v or "") for k, v in result.items()}
    except Exception:
        pass
    return {"reason": "", "activated": "", "read_error": "unavailable"}


def emit() -> bool:
    global _LAST_SIGNATURE
    try:
        ks, status = _status()
        active = bool(status.get("is_active"))
        history = list(status.get("recent_history") or [])
        latest = history[-1] if history and isinstance(history[-1], dict) else {}
        causal_reason, causal_source = _causal(status)
        marker = _marker_meta(ks)
        v143_meta = status.get("_nija_persisted_cause_v143")
        signature = "|".join(
            (
                str(active),
                _bounded(latest.get("source"), 64),
                _bounded(latest.get("reason"), 256),
                _bounded(causal_source, 64),
                _bounded(causal_reason, 256),
                _bounded(marker.get("reason"), 256),
                _bounded(v143_meta, 256),
            )
        )
        with _LOCK:
            if signature == _LAST_SIGNATURE:
                return True
            _LAST_SIGNATURE = signature

        LOGGER.critical(
            "KILL_SWITCH_CAUSAL_V215 marker=%s active=%s latest_source=%s "
            "latest_reason=%s causal_source=%s causal_reason=%s marker_reason=%s "
            "marker_activated=%s marker_read_error=%s v143_meta=%s "
            "state_mutated=false marker_mutated=false recovery_attempted=false "
            "execution_authority_unchanged=true trading_fail_closed=true",
            MARKER,
            str(active).lower(),
            _bounded(latest.get("source"), 64),
            _bounded(latest.get("reason"), 512),
            _bounded(causal_source, 64),
            _bounded(causal_reason, 512),
            _bounded(marker.get("reason"), 512),
            _bounded(marker.get("activated"), 128),
            _bounded(marker.get("read_error"), 128),
            _bounded(v143_meta, 512),
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_CAUSAL_V215_ERROR marker=%s err=%s:%s state_mutated=false "
            "trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def install() -> bool:
    os.environ[_FLAG] = "1"
    emit()
    LOGGER.critical(
        "KILL_SWITCH_CAUSAL_DIAGNOSTIC_V215_READY marker=%s ready=true "
        "bounded_read_only=true state_mutated=false marker_mutated=false "
        "recovery_eligibility_unchanged=true execution_authority_unchanged=true "
        "safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "emit", "install", "install_import_hook", "_bounded"]
