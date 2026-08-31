"""Platform position-sync activation isolation v320.

Production generation 5053 proved all three PLATFORM brokers (Coinbase, Kraken,
OKX) had current authoritative v285 snapshots, complete reconciliation and
protective exits.  Canonical ``position_sync_ready`` nevertheless regressed to
false when Daivon/Tania user-account Kraken reconciliation remained incomplete.
That contradicts the existing v281/v282 contract, which explicitly keeps user
entries fail closed while preserving ``platform_activation_unchanged=true`` and
``user_execution_isolation_preserved=true``.

v320 restores that intended boundary without weakening position proof:

* v285 remains the proof owner.  Its strong proof still requires current
  authoritative fetch, adoption and non-stale snapshot truth.
* after v285 installs its strong ``v95.position_sync_status`` wrapper, v320
  filters only the *canonical platform activation* status to ``platform:*``
  rows.  Every connected platform row must still be strong-proof ready.
* v281/v282/v283 retain the all-account denominator and continue to block each
  unproven user account from new entries while preserving exits.

No user readiness is fabricated and no user broker is marked synchronized.
No platform broker can be omitted from the platform denominator.  Writer,
nonce, capital, risk, kill-switch, order/fill, snapshot-age and protective-exit
gates are unchanged.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_platform_position_sync_isolation_v320")
MARKER = "20260831-platform-position-sync-isolation-v320"
RELEASE_ID = "20260831-runtime-convergence-v320"
_READY_FLAG = "NIJA_RUNTIME_PLATFORM_POSITION_SYNC_ISOLATION_V320_READY"
_PATCH_ATTR = "_nija_platform_position_sync_isolation_v320"
_IMPORT_HOOK_FLAG = "_NIJA_PLATFORM_POSITION_SYNC_ISOLATION_V320_IMPORT_HOOK"
_LOCK = threading.RLock()


def _is_v285_strong_status(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(64):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        owner = getattr(current, "__globals__", {}) or {}
        if (
            owner.get("MARKER") == "20260829-authoritative-position-coverage-v285"
            and str(getattr(current, "__name__", "")) == "position_sync_status_v285"
        ):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_v95_after_v285() -> bool:
    """Filter canonical activation status only after v285 strong proof exists."""
    try:
        v95 = importlib.import_module("bot.position_sync_core_handoff_v95_patch")
    except Exception:
        return False
    current = getattr(v95, "position_sync_status", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    if not _is_v285_strong_status(current):
        # Never replace v285's strong proof with the weaker historical latch.
        return False
    original = current

    @wraps(original)
    def position_sync_status_v320(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
        _all_ready, _all_pending, all_status = original(manager)
        status = {
            str(name): bool(ready)
            for name, ready in dict(all_status or {}).items()
            if str(name).startswith("platform:")
        }
        pending = sorted(name for name, ready in status.items() if not ready)
        ready = bool(status) and not pending

        user_status = {
            str(name): bool(value)
            for name, value in dict(all_status or {}).items()
            if str(name).startswith("user:")
        }
        user_pending = sorted(name for name, value in user_status.items() if not value)
        try:
            setattr(manager, "_nija_platform_position_sync_status_v320", dict(status))
            setattr(manager, "_nija_user_position_sync_status_v320", dict(user_status))
        except Exception:
            pass

        log = LOGGER.info if ready else LOGGER.critical
        log(
            "PLATFORM_POSITION_SYNC_ISOLATION_V320_STATE marker=%s ready=%s "
            "platform_pending=%s platform_status=%s user_pending=%s "
            "v285_strong_proof_required=true all_connected_platform_required=true "
            "user_entries_fail_closed=true user_exits_preserved=true "
            "user_readiness_fabricated=false platform_readiness_fabricated=false "
            "platform_activation_user_isolated=true safety_gates_bypassed=false",
            MARKER,
            str(bool(ready)).lower(),
            pending,
            status,
            user_pending,
        )
        return bool(ready), pending, status

    position_sync_status_v320.__name__ = "position_sync_status_v320"
    setattr(position_sync_status_v320, _PATCH_ATTR, True)
    setattr(position_sync_status_v320, "__wrapped__", original)
    v95.position_sync_status = position_sync_status_v320
    return True


def _patch_v285(module: ModuleType) -> bool:
    current = getattr(module, "_patch_v95_status", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        # Re-assert in case another idempotent installer replay replaced v95.
        _patch_v95_after_v285()
        return True
    original = current

    @wraps(original)
    def patch_v95_status_v320() -> bool:
        result = original()
        if result is False:
            return False
        if not _patch_v95_after_v285():
            LOGGER.critical(
                "PLATFORM_POSITION_SYNC_ISOLATION_V320_DEFERRED marker=%s "
                "reason=v285_strong_status_not_yet_active fail_closed=true",
                MARKER,
            )
            return False
        return True

    patch_v95_status_v320.__name__ = "patch_v95_status_v320"
    setattr(patch_v95_status_v320, _PATCH_ATTR, True)
    setattr(patch_v95_status_v320, "__wrapped__", original)
    module._patch_v95_status = patch_v95_status_v320

    # If v285 was already installed before v320 appeared, apply the isolation
    # adapter immediately to the existing strong status wrapper.
    _patch_v95_after_v285()
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in (
        "bot.runtime_authoritative_position_coverage_v285_patch",
        "runtime_authoritative_position_coverage_v285_patch",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_v285(module) or changed
    return changed


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_platform_position_sync_isolation_v320"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        _patch_loaded()
        if not bool(getattr(builtins, _IMPORT_HOOK_FLAG, False)):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                text = str(name or "")
                if "runtime_authoritative_position_coverage_v285" in text:
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _IMPORT_HOOK_FLAG, True)

        manifest = _register_manifest()
        ready = bool(manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "PLATFORM_POSITION_SYNC_ISOLATION_V320_NOT_READY marker=%s "
                "reason=manifest_registration_failed trading_fail_closed=true "
                "user_isolation_not_claimed=true safety_gates_bypassed=false",
                MARKER,
            )
            return False

        LOGGER.critical(
            "PLATFORM_POSITION_SYNC_ISOLATION_V320_READY marker=%s ready=true "
            "v285_strong_proof_preserved=true all_connected_platform_required=true "
            "v281_v282_v283_all_account_coverage_unchanged=true "
            "user_entries_fail_closed=true user_exits_preserved=true "
            "user_readiness_fabricated=false platform_readiness_fabricated=false "
            "writer_nonce_capital_risk_killswitch_order_fill_snapshot_ttl_unchanged=true "
            "forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_v285",
    "_patch_v95_after_v285",
    "_is_v285_strong_status",
]
