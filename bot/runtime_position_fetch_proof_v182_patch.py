"""Reassert authoritative platform position-fetch proof after wrapper churn.

Production on 2026-08-21 showed v96 reporting adopted platform position snapshots
while v146 correctly rejected readiness because one or more brokers lacked the
independent ``_startup_position_sync_fetch_ok`` proof.  The startup adopter is
heavily wrapped and several wrappers use ``functools.wraps``; copied marker
attributes can therefore make a later installer believe the v98 fetch-proof
wrapper is present even when the exact v98 wrapper is no longer in the active
call chain.

v182 repairs only that wrapper/proof handoff.  It identifies the exact v98
wrapper by its function-owner globals, reasserts it on the canonical startup
adopter when missing, makes platform discovery require both adoption and fetch
proof, fail-closes a worker that returns adopted without fetch proof, and
reasserts the exact v108 MABM refresh dispatcher so a broker missing proof gets
a real authoritative retry after later wrapper churn.

No position, connectivity, capital, writer/nonce authority, kill switch, risk
state, activation state, or execution permission is fabricated or promoted.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_position_fetch_proof_v182")
MARKER = "20260821-runtime-position-fetch-proof-v182"
RELEASE_ID = "20260821-runtime-convergence-v182"
_READY_FLAG = "NIJA_RUNTIME_POSITION_FETCH_PROOF_V182_READY"
_PATCH_ATTR = "_nija_runtime_position_fetch_proof_v182"
_V98_PATCH_ATTR = "_nija_position_sync_failure_truth_v98"
_V98_MARKER = "20260815-position-sync-failure-truth-v98"
_V98_MODULE_NAMES = {
    "bot.position_sync_failure_truth_v98_patch",
    "position_sync_failure_truth_v98_patch",
}
_LOCK = threading.RLock()


def _chain_has_exact_v98_wrapper(callable_obj: Any) -> bool:
    """Prove the actual v98 owner is in the chain; ignore wraps-copied markers."""
    seen: set[int] = set()
    current = callable_obj
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _V98_PATCH_ATTR, False)):
            owner = getattr(current, "__globals__", {}) or {}
            if (
                str(owner.get("__name__", "")) in _V98_MODULE_NAMES
                and str(owner.get("MARKER", "")) == _V98_MARKER
            ):
                return True
        current = getattr(current, "__wrapped__", None)
    return False


def _chain_has_exact_v182_wrapper(callable_obj: Any, expected_name: str) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PATCH_ATTR, False)):
            owner = getattr(current, "__globals__", {}) or {}
            if owner.get("MARKER") == MARKER and str(getattr(current, "__name__", "")) == expected_name:
                return True
        current = getattr(current, "__wrapped__", None)
    return False


def _startup_sync_module() -> ModuleType:
    try:
        return importlib.import_module("bot.startup_position_sync")
    except ImportError:
        return importlib.import_module("startup_position_sync")


def _v98_module() -> ModuleType:
    try:
        return importlib.import_module("bot.position_sync_failure_truth_v98_patch")
    except ImportError:
        return importlib.import_module("position_sync_failure_truth_v98_patch")


def _v108_module() -> ModuleType:
    return importlib.import_module("bot.platform_position_sync_v108_patch")


def _reassert_v98_adopter() -> tuple[bool, str]:
    """Ensure the canonical adopter contains the exact v98 fetch-proof wrapper."""
    try:
        sync_module = _startup_sync_module()
        v98 = _v98_module()
        current = getattr(sync_module, "_adopt_broker_positions", None)
        if not callable(current):
            return False, "canonical_adopter_missing"
        if _chain_has_exact_v98_wrapper(current):
            return True, "exact_v98_already_present"

        marker = str(getattr(v98, "_ADOPT_ATTR", _V98_PATCH_ATTR) or _V98_PATCH_ATTR)
        if bool(getattr(current, marker, False)):
            try:
                delattr(current, marker)
            except Exception:
                return False, "copied_v98_marker_not_clearable"

        patcher = getattr(v98, "_patch_startup_sync", None)
        if not callable(patcher) or not bool(patcher(sync_module)):
            return False, "v98_repatch_failed"
        updated = getattr(sync_module, "_adopt_broker_positions", None)
        if not _chain_has_exact_v98_wrapper(updated):
            return False, "exact_v98_not_in_chain_after_repatch"
        LOGGER.critical(
            "POSITION_FETCH_PROOF_V182_V98_REASSERTED marker=%s exact_owner=true "
            "copied_marker_false_positive_blocked=true synthetic_success=false safety_gates_bypassed=false",
            MARKER,
        )
        return True, "v98_reasserted"
    except Exception as exc:
        return False, f"v98_reassert_error:{type(exc).__name__}:{exc}"


def _connected_platform_brokers_requiring_proof(manager: Any) -> list[tuple[str, Any]]:
    """Return connected platform brokers missing adoption OR fetch proof."""
    found: list[tuple[str, Any]] = []
    try:
        platform = getattr(manager, "platform_brokers", {}) or {}
        if callable(platform):
            platform = platform()
        for broker_type, broker in dict(platform or {}).items():
            if broker is None or not bool(getattr(broker, "connected", False)):
                continue
            adopted = bool(getattr(broker, "_startup_position_sync_adopted", False))
            fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None) is True
            if adopted and fetch_ok:
                continue
            name = str(getattr(broker_type, "value", broker_type) or "unknown").lower()
            found.append((name, broker))
    except Exception as exc:
        LOGGER.warning(
            "POSITION_FETCH_PROOF_V182_DISCOVERY_FAILED marker=%s error=%s:%s fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
    return found


def _patch_discovery() -> bool:
    try:
        v108 = _v108_module()
        current = getattr(v108, "_connected_unsynced_platform_brokers", None)
        if not callable(current):
            return False
        if _chain_has_exact_v182_wrapper(current, "discovery_v182"):
            return True
        original = current

        @wraps(original)
        def discovery_v182(manager: Any) -> list[tuple[str, Any]]:
            return _connected_platform_brokers_requiring_proof(manager)

        discovery_v182.__name__ = "discovery_v182"
        setattr(discovery_v182, _PATCH_ATTR, True)
        setattr(discovery_v182, "__wrapped__", original)
        v108._connected_unsynced_platform_brokers = discovery_v182
        return True
    except Exception:
        return False


def _publish_fail_closed(v108: ModuleType, manager: Any, broker_name: str, broker: Any, key: tuple[int, int], reason: str) -> None:
    try:
        setattr(broker, "_startup_position_sync_adopted", False)
        setattr(broker, "_startup_position_sync_fetch_ok", False)
        setattr(broker, "_startup_position_sync_error", reason)
    except Exception:
        pass
    try:
        v108._publish_readiness(manager, source=f"v182:{broker_name}:{reason}")
    except Exception:
        pass
    active = getattr(v108, "_ACTIVE", None)
    lock = getattr(v108, "_LOCK", None)
    if isinstance(active, set) and lock is not None:
        with lock:
            active.discard(key)


def _patch_worker() -> bool:
    try:
        v108 = _v108_module()
        current = getattr(v108, "_worker", None)
        if not callable(current):
            return False
        if _chain_has_exact_v182_wrapper(current, "worker_v182"):
            return True
        original = current

        @wraps(original)
        def worker_v182(manager: Any, broker_name: str, broker: Any, key: tuple[int, int], trigger: str) -> None:
            proof_ok, detail = _reassert_v98_adopter()
            if not proof_ok:
                reason = f"v98_fetch_proof_wrapper_unavailable:{detail}"
                LOGGER.critical(
                    "POSITION_FETCH_PROOF_V182_WORKER_BLOCKED marker=%s broker=%s trigger=%s "
                    "reason=%s trading_fail_closed=true synthetic_success=false",
                    MARKER,
                    broker_name,
                    trigger,
                    reason,
                )
                _publish_fail_closed(v108, manager, broker_name, broker, key, reason)
                return

            original(manager, broker_name, broker, key, trigger)
            adopted = bool(getattr(broker, "_startup_position_sync_adopted", False))
            fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None) is True
            if adopted and not fetch_ok:
                reason = "adopted_without_authoritative_fetch_proof"
                LOGGER.critical(
                    "POSITION_FETCH_PROOF_V182_POSTCHECK_REVOKED marker=%s broker=%s trigger=%s "
                    "adopted=true fetch_ok=false trading_fail_closed=true synthetic_success=false",
                    MARKER,
                    broker_name,
                    trigger,
                )
                _publish_fail_closed(v108, manager, broker_name, broker, key, reason)

        worker_v182.__name__ = "worker_v182"
        setattr(worker_v182, _PATCH_ATTR, True)
        setattr(worker_v182, "__wrapped__", original)
        v108._worker = worker_v182
        return True
    except Exception:
        return False


def _reassert_v108_dispatch_hook() -> tuple[bool, str]:
    """Restore the exact v108 MABM refresh dispatcher after wrapper churn."""
    try:
        v108 = _v108_module()
        patch_loaded = getattr(v108, "_patch_loaded", None)
        if not callable(patch_loaded):
            return False, "v108_patch_loaded_unavailable"
        ready = bool(patch_loaded())
        if not ready:
            return False, "v108_mabm_not_loaded_or_patch_failed"

        exact = getattr(v108, "_chain_has_exact_refresh_hook", None)
        if not callable(exact):
            return False, "v108_exact_refresh_verifier_unavailable"

        verified = False
        for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            cls = getattr(module, "MultiAccountBrokerManager", None)
            current = getattr(cls, "refresh_capital_authority", None) if isinstance(cls, type) else None
            if callable(current) and bool(exact(current)):
                verified = True
                break
        if not verified:
            return False, "exact_v108_refresh_hook_not_verified"

        LOGGER.critical(
            "POSITION_FETCH_PROOF_V182_V108_DISPATCH_REASSERTED marker=%s "
            "exact_refresh_owner=true copied_marker_false_positive_blocked=true "
            "authoritative_retry_only=true synthetic_success=false safety_gates_bypassed=false",
            MARKER,
        )
        return True, "exact_v108_refresh_hook_ready"
    except Exception as exc:
        return False, f"v108_dispatch_reassert_error:{type(exc).__name__}:{exc}"


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_position_fetch_proof_v182"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        v98_ok, v98_detail = _reassert_v98_adopter()
        discovery_ok = _patch_discovery()
        worker_ok = _patch_worker()
        dispatch_ok, dispatch_detail = _reassert_v108_dispatch_hook()
        manifest_ok = _patch_release_manifest()
        ready = bool(v98_ok and discovery_ok and worker_ok and dispatch_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_POSITION_FETCH_PROOF_V182_FAILED marker=%s v98_ok=%s v98_detail=%s "
                "discovery_ok=%s worker_ok=%s dispatch_ok=%s dispatch_detail=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(v98_ok).lower(),
                v98_detail,
                str(discovery_ok).lower(),
                str(worker_ok).lower(),
                str(dispatch_ok).lower(),
                dispatch_detail,
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_POSITION_FETCH_PROOF_V182 marker=%s ready=true exact_v98_owner_required=true "
            "adopted_and_fetch_proof_required=true exact_v108_refresh_hook_required=true "
            "copied_marker_false_positive_blocked=true synthetic_success=false forced_activation=false safety_gates_bypassed=false",
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
    "_chain_has_exact_v98_wrapper",
    "_reassert_v98_adopter",
    "_connected_platform_brokers_requiring_proof",
    "_patch_discovery",
    "_patch_worker",
    "_reassert_v108_dispatch_hook",
    "_patch_release_manifest",
]