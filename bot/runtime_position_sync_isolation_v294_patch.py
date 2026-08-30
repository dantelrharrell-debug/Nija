"""Restore platform/user position-sync isolation without weakening account safety (v294).

README production recovery evidence and the v282 account-local eligibility contract
require two distinct truths:

* canonical platform activation is gated by authoritative PLATFORM broker position
  proof; and
* each USER account remains independently entry-blocked until its own authoritative
  position/capital proof is current.

v285 strengthens all-account position/protective-exit coverage, but it also wraps
v95 ``position_sync_status`` with a status containing every connected platform and
user broker. v96 publishes that status as the global ``position_sync_ready`` key.
Consequently a single user-local proof failure can revoke the platform execution
commit even though v282 explicitly promises ``platform_activation_unchanged``.

v294 restores the intended isolation boundary. It wraps the already-strengthened
v95/v285 status function and publishes only ``platform:*`` rows to the canonical
platform activation certificate. User rows are not declared ready or discarded:
v282 continues to block each user's new entries locally, while v281/v285 continue
to audit all expected accounts and protective exits independently.

No position, capital, connectivity, cost basis, execution, order, fill, or safety
truth is fabricated. An unready platform broker still blocks canonical activation.
A missing platform broker set remains fail closed. User exits and all-account
coverage remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_position_sync_isolation_v294")
MARKER = "20260830-position-sync-isolation-v294"
RELEASE_ID = "20260830-runtime-convergence-v294"
_READY_FLAG = "NIJA_RUNTIME_POSITION_SYNC_ISOLATION_V294_READY"
_PATCH_ATTR = "_nija_position_sync_isolation_v294"
_LOCK = threading.RLock()
_LAST_SIGNATURE = ""


def _v95() -> Any:
    return importlib.import_module("bot.position_sync_core_handoff_v95_patch")


def _is_platform_account(name: Any) -> bool:
    return str(name or "").strip().lower().startswith("platform:")


def _is_user_account(name: Any) -> bool:
    return str(name or "").strip().lower().startswith("user:")


def _chain_has_patch(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(96):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PATCH_ATTR, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _emit_isolation(platform_status: dict[str, bool], user_status: dict[str, bool]) -> None:
    global _LAST_SIGNATURE
    platform_pending = tuple(sorted(name for name, ready in platform_status.items() if not ready))
    user_pending = tuple(sorted(name for name, ready in user_status.items() if not ready))
    signature = repr((tuple(sorted(platform_status.items())), tuple(sorted(user_status.items()))))
    with _LOCK:
        if signature == _LAST_SIGNATURE:
            return
        _LAST_SIGNATURE = signature
    log = LOGGER.critical if platform_pending else LOGGER.info
    log(
        "POSITION_SYNC_ISOLATION_V294_STATE marker=%s platform_ready=%s "
        "platform_status=%s platform_pending=%s user_status=%s user_pending=%s "
        "user_pending_revokes_platform=false user_entries_remain_account_local_fail_closed=true "
        "all_account_exit_coverage_unchanged=true synthetic_success=false safety_gates_bypassed=false",
        MARKER,
        str(bool(platform_status) and not platform_pending).lower(),
        platform_status,
        platform_pending,
        user_status,
        user_pending,
    )


def _patch_v95_status() -> bool:
    try:
        v95 = _v95()
    except Exception:
        return False
    current = getattr(v95, "position_sync_status", None)
    if not callable(current):
        return False
    if _chain_has_patch(current):
        return True
    original = current

    @wraps(original)
    def position_sync_status_v294(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
        _all_ready, _all_pending, raw_status = original(manager)
        status = dict(raw_status or {}) if isinstance(raw_status, dict) else {}
        platform_status = {
            str(name): bool(ready)
            for name, ready in status.items()
            if _is_platform_account(name)
        }
        user_status = {
            str(name): bool(ready)
            for name, ready in status.items()
            if _is_user_account(name)
        }
        pending = sorted(name for name, ready in platform_status.items() if not ready)
        ready = bool(platform_status) and not pending
        _emit_isolation(platform_status, user_status)
        return ready, pending, platform_status

    position_sync_status_v294.__name__ = "position_sync_status_v294"
    setattr(position_sync_status_v294, _PATCH_ATTR, True)
    setattr(position_sync_status_v294, "__wrapped__", original)
    v95.position_sync_status = position_sync_status_v294
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_position_sync_isolation_v294"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    patched = _patch_v95_status()
    return {"ready": bool(patched), "platform_user_isolation_patched": bool(patched)}


def install() -> bool:
    manifest_ok = _register_manifest()
    patched = _patch_v95_status()
    ready = bool(manifest_ok and patched)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_POSITION_SYNC_ISOLATION_V294_%s marker=%s ready=%s "
        "canonical_position_sync_platform_only=true user_entry_eligibility_v282_preserved=true "
        "all_account_exit_coverage_v281_v285_preserved=true platform_failure_still_blocks=true "
        "missing_platform_set_fail_closed=true position_success_fabricated=false "
        "execution_proof_fabricated=false forced_trade=false forced_activation=false "
        "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_is_platform_account",
    "_is_user_account",
    "_patch_v95_status",
]
