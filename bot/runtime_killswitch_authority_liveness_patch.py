"""Preserve heartbeat kill-switch causality and canonical writer ownership.

This runtime patch is deliberately non-authoritative: it never activates or
clears the kill switch, never grants execution authority, never resumes SEAK,
and never releases the canonical writer lease.  It only:

* preserves AUTOMATIC provenance when an existing caller materializes a
  heartbeat-owned emergency stop through ``KillSwitch.activate`` without an
  explicit source; and
* replaces the legacy v58 canonical-path stalled-writer diagnostic with a
  throttled owner/phase diagnostic while keeping destructive release disabled.

The v132 durability worker periodically reasserts these wrappers so later
compatibility churn cannot silently restore the old behavior.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_killswitch_authority_liveness")
MARKER = "20260817-runtime-killswitch-authority-liveness-v1"
_FLAG = "NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_READY"
_LOCK = threading.RLock()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_KILL_PATCH_ATTR = "_nija_heartbeat_killswitch_provenance_v1"
_HEARTBEAT_PATCH_ATTR = "_nija_heartbeat_owned_stop_provenance_v1"
_WRITER_PATCH_ATTR = "_nija_canonical_writer_release_diagnostic_v1"
_OWNED_STOP_ENV = "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP"
_OWNED_REASON_ENV = "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP_REASON"
_LAST_WRITER_DIAGNOSTIC: dict[str, float] = {}
_ANNOUNCED = False


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _heartbeat_failure_reason(reason: object) -> bool:
    text = str(reason or "").strip().upper()
    if not text:
        return False
    heartbeat = "AUTHORITY_HEARTBEAT_EXPIRED" in text or "AUTHORITY HEARTBEAT EXPIRED" in text
    dead_core = "CORE_THREAD_DEAD" in text or "NIJA_CORE_THREAD_ALIVE" in text
    return heartbeat and dead_core


def _normalized_activation_source(reason: object, source: object) -> str:
    """Return AUTOMATIC only for a runtime-proven heartbeat-owned stop.

    ``KillSwitch.activate`` historically defaults ``source`` to MANUAL.  That
    default is correct for generic callers, so it is preserved unless the
    authority-heartbeat callback has already published its owned-stop marker
    and the activation reason carries the matching heartbeat/core-death proof.
    """

    normalized = str(source or "MANUAL").strip() or "MANUAL"
    if normalized.upper() != "MANUAL":
        return normalized
    if not _truthy_env(_OWNED_STOP_ENV):
        return normalized
    if not _heartbeat_failure_reason(reason):
        return normalized
    return "AUTOMATIC"


def _patch_kill_switch() -> bool:
    module = importlib.import_module("bot.kill_switch")
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "activate", None)
    if not callable(current):
        return False
    if getattr(current, _KILL_PATCH_ATTR, False):
        return True

    @wraps(current)
    def activate_with_heartbeat_provenance(
        self: Any,
        reason: str,
        source: str = "MANUAL",
    ) -> Any:
        normalized = _normalized_activation_source(reason, source)
        if normalized != str(source or "MANUAL").strip():
            LOGGER.critical(
                "HEARTBEAT_KILL_SWITCH_SOURCE_NORMALIZED marker=%s "
                "source_before=%s source_after=%s reason=%s",
                MARKER,
                source or "MANUAL",
                normalized,
                reason,
            )
        return current(self, reason, normalized)

    setattr(activate_with_heartbeat_provenance, _KILL_PATCH_ATTR, True)
    cls.activate = activate_with_heartbeat_provenance
    return True


def _patch_authority_heartbeat_callback() -> bool:
    module = importlib.import_module("bot.authority_heartbeat")
    current = getattr(module, "_default_lockdown_callback", None)
    if not callable(current):
        return False
    if getattr(current, _HEARTBEAT_PATCH_ATTR, False):
        return True

    @wraps(current)
    def heartbeat_owned_lockdown(reason: str) -> Any:
        os.environ[_OWNED_STOP_ENV] = "1"
        os.environ[_OWNED_REASON_ENV] = str(reason or "unknown")
        return current(reason)

    setattr(heartbeat_owned_lockdown, _HEARTBEAT_PATCH_ATTR, True)
    module._default_lockdown_callback = heartbeat_owned_lockdown

    existing = getattr(module, "_monitor_instance", None)
    if existing is not None:
        callback = getattr(existing, "_lockdown_callback", None)
        if callback is current:
            existing._lockdown_callback = heartbeat_owned_lockdown
    return True


def _writer_diagnostic_interval_s() -> float:
    try:
        return max(
            60.0,
            float(os.environ.get("NIJA_CANONICAL_WRITER_RELEASE_DIAGNOSTIC_INTERVAL_S", "300") or 300.0),
        )
    except (TypeError, ValueError):
        return 300.0


def _patch_stalled_writer_release_guard() -> bool:
    guard = importlib.import_module("bot.stalled_writer_release_guard_v22")
    v58 = importlib.import_module("bot.final_production_activation_repair_v58_patch")
    current = getattr(guard, "_should_release", None)
    if not callable(current):
        return False
    if getattr(current, _WRITER_PATCH_ATTR, False):
        return True

    @wraps(current)
    def should_release_with_canonical_owner(
        snapshot: Any,
        elapsed_s: float,
        timeout_s: float,
    ) -> bool:
        canonical = bool(v58._canonical_fast_path())
        if not canonical:
            return bool(current(snapshot, elapsed_s, timeout_s))

        # v58 intentionally made the canonical Render path diagnostic-only:
        # bot_main owns shutdown/re-election and this legacy guard must never
        # compare-and-delete a healthy writer lease behind it.  Preserve that
        # contract, but stop describing a live registered core as "startup".
        if elapsed_s >= timeout_s:
            core_live = bool(v58._canonical_core_registered())
            phase = "runtime_core_live" if core_live else "startup_handoff"
            generation = str(getattr(snapshot, "generation", "0") or "0")
            state = str(getattr(snapshot, "state", "unknown") or "unknown")
            key = f"{generation}:{phase}:{state}"
            now = time.monotonic()
            last = _LAST_WRITER_DIAGNOSTIC.get(key, 0.0)
            if now - last >= _writer_diagnostic_interval_s():
                _LAST_WRITER_DIAGNOSTIC[key] = now
                LOGGER.warning(
                    "WRITER_RELEASE_SUPPRESSED_BY_CANONICAL_OWNER marker=%s "
                    "phase=%s elapsed_s=%.1f timeout_s=%.1f state=%s generation=%s "
                    "writer_release_owner=bot_main core_live=%s destructive_release=false",
                    MARKER,
                    phase,
                    elapsed_s,
                    timeout_s,
                    state,
                    generation,
                    str(core_live).lower(),
                )
        return False

    setattr(should_release_with_canonical_owner, _WRITER_PATCH_ATTR, True)
    guard._should_release = should_release_with_canonical_owner
    return True


def install() -> bool:
    """Install/reassert all non-authoritative convergence wrappers."""
    global _ANNOUNCED
    with _LOCK:
        try:
            ok = bool(
                _patch_authority_heartbeat_callback()
                and _patch_kill_switch()
                and _patch_stalled_writer_release_guard()
            )
        except Exception as exc:
            os.environ.pop(_FLAG, None)
            LOGGER.critical(
                "RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_INSTALL_FAILED marker=%s "
                "err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False

        if not ok:
            os.environ.pop(_FLAG, None)
            return False

        os.environ[_FLAG] = "1"
        if not _ANNOUNCED:
            _ANNOUNCED = True
            LOGGER.critical(
                "RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_INSTALLED marker=%s "
                "heartbeat_source_preserved=true generic_manual_source_unchanged=true "
                "kill_switch_auto_clear=false writer_release=false execution_authority_unchanged=true",
                MARKER,
            )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_heartbeat_failure_reason",
    "_normalized_activation_source",
    "_patch_authority_heartbeat_callback",
    "_patch_kill_switch",
    "_patch_stalled_writer_release_guard",
]
