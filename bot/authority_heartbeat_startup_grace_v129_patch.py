"""Prevent pre-core startup from being misclassified as core death.

Production v128 proved that the authority heartbeat starts before canonical core
registration. During that legitimate window, ``NIJA_CORE_THREAD_ALIVE=0`` was
counted as ``core_thread_dead`` and three retries permanently halted SEAK even
though the core later registered and stayed alive.

v129 preserves fail-closed authority semantics. It suppresses only the *core
liveness flag* while canonical core registration has never been observed, then
runs the original authority check in full so Redis, fencing, generation, writer
renewal, and all other authority checks still execute. Once registration has
been observed, core liveness is enforced permanently for the life of the
process. No SEAK resume, readiness fabrication, execution grant, or shutdown
clearing is performed here.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.authority_heartbeat_startup_grace_v129")
MARKER = "20260816-authority-heartbeat-startup-grace-v129"
RELEASE_ID = "20260816-runtime-convergence-v129"
_FLAG = "NIJA_AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129_INSTALLED"
_PATCH_ATTR = "_nija_authority_heartbeat_startup_grace_v129"
_LOCK = threading.RLock()
_INSTALLED = False
_CORE_REGISTRATION_OBSERVED = False


def _canonical_import(name: str) -> ModuleType:
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        return existing
    bootstrap = getattr(importlib, "_bootstrap", None)
    gcd_import = getattr(bootstrap, "_gcd_import", None) if bootstrap is not None else None
    if not callable(gcd_import):
        raise RuntimeError("canonical_import_primitive_unavailable")
    module = gcd_import(name)
    if not isinstance(module, ModuleType):
        raise RuntimeError(f"canonical_import_invalid_module:{name}")
    return module


def _writer_singleton() -> Any:
    module = _canonical_import("bot.entrypoint_writer_authority")
    getter = getattr(module, "get_entrypoint_writer_authority", None)
    return getter() if callable(getter) else None


def _core_registration_state() -> tuple[bool, bool, str]:
    """Return (observed_once, registered_now, reason) without mutating runtime state."""
    global _CORE_REGISTRATION_OBSERVED
    singleton = _writer_singleton()
    registered_now = bool(getattr(singleton, "_core_thread_registered", False)) if singleton else False
    if registered_now:
        _CORE_REGISTRATION_OBSERVED = True
    reason = "registered" if registered_now else "startup_not_registered"
    return _CORE_REGISTRATION_OBSERVED, registered_now, reason


def _patch_authority_check() -> bool:
    heartbeat = _canonical_import("bot.authority_heartbeat")
    current = getattr(heartbeat, "_check_authority_once", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def _check_authority_once_v129(timeout_s: float):
        observed_once, registered_now, reason = _core_registration_state()
        core_raw = os.environ.get("NIJA_CORE_THREAD_ALIVE")
        core_false = str(core_raw or "").strip().lower() in {"0", "false", "no", "off", "disabled"}

        # Only neutralize the pre-registration core flag. The original check is
        # still executed in full, so writer lease, fencing, Redis, renewal proof,
        # and generation checks remain unchanged and fail closed as before.
        if core_false and not observed_once and not registered_now:
            os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
            try:
                ok, err = current(timeout_s)
            finally:
                if core_raw is None:
                    os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
                else:
                    os.environ["NIJA_CORE_THREAD_ALIVE"] = core_raw
            if ok:
                LOGGER.warning(
                    "AUTHORITY_HEARTBEAT_V129_PRECORE_DEFERRED marker=%s reason=%s "
                    "core_registration_observed=false redis_authority_verified=true "
                    "failure_counter_unchanged=true execution_authority_unchanged=true",
                    MARKER,
                    reason,
                )
            return ok, err

        return current(timeout_s)

    setattr(_check_authority_once_v129, _PATCH_ATTR, True)
    setattr(_check_authority_once_v129, "__wrapped__", current)
    heartbeat._check_authority_once = _check_authority_once_v129
    return True


def _patch_release_manifest() -> bool:
    manifest = _canonical_import("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["authority_heartbeat_startup_grace_v129"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED and os.environ.get(_FLAG) == "1":
            return True
        try:
            check_ok = _patch_authority_check()
            manifest_ok = _patch_release_manifest()
        except Exception as exc:
            LOGGER.critical(
                "AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129_INSTALL_FAILED marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            check_ok = manifest_ok = False

        if not (check_ok and manifest_ok):
            os.environ.pop(_FLAG, None)
            _INSTALLED = False
            return False

        os.environ[_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "AUTHORITY_HEARTBEAT_STARTUP_GRACE_V129_INSTALLED marker=%s release=%s "
            "precore_core_liveness_deferred=true redis_authority_still_verified=true "
            "post_registration_core_death_fatal=true seak_auto_resume=false "
            "shutdown_clear=false readiness_synthetic=false execution_authority_unchanged=true",
            MARKER,
            RELEASE_ID,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_core_registration_state",
]
