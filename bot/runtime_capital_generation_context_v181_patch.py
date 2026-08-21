"""Restore canonical v142 generation context without weakening rollover fencing.

Production on 2026-08-21 showed a complete three-broker proactive refresh reach
CapitalAuthority after a v142 coordinator rollover, but the publication arrived
at the v142 fence with no thread-local generation tag and was rejected as
``UNTAGGED_AFTER_ROLLOVER``.  The broker aggregation itself was complete and the
current canonical coordinator worker was still the owner.

v181 repairs only that handoff.  When the exact v142 publication wrapper is in
the active call chain, an authorized publication may temporarily recover the
wrapper owner's generation context only if the current thread is exactly the
canonical manager's current coordinator worker, that worker is still in-flight,
its generation equals v142's active generation, and it has not timed out.
Retired, detached, unknown, and unauthorized publishers remain fenced.

No capital value, freshness timestamp, publication expiry, writer/nonce/risk
state, kill switch, activation state, or execution permission is changed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_generation_context_v181")
MARKER = "20260821-runtime-capital-generation-context-v181"
RELEASE_ID = "20260821-runtime-convergence-v181"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_GENERATION_CONTEXT_V181_READY"
_PATCH_ATTR = "_nija_runtime_capital_generation_context_v181"
_LOCK = threading.RLock()
_MISSING = object()


def _find_v142_publication_wrapper(callable_obj: Any) -> Any:
    """Return the exact v142 publish wrapper from a wrapped call chain."""
    seen: set[int] = set()
    current = callable_obj
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return None
        seen.add(id(current))
        if (
            str(getattr(current, "__name__", "")) == "publish_snapshot_v142"
            and bool(getattr(current, "_nija_capital_publication_liveness_v142", False))
        ):
            return current
        current = getattr(current, "__wrapped__", None)
    return None


def _canonical_generation_from_v142_wrapper(wrapper: Any) -> tuple[int | None, str, Any]:
    """Prove the current thread is the live canonical v142 coordinator worker."""
    if not callable(wrapper):
        return None, "v142_wrapper_missing", None
    owner = getattr(wrapper, "__globals__", {}) or {}
    local = owner.get("_LOCAL")
    generation_state = owner.get("_generation_state")
    canonical_manager = owner.get("_canonical_manager")
    if local is None or not callable(generation_state) or not callable(canonical_manager):
        return None, "v142_owner_context_missing", local
    if getattr(local, "refresh_generation", None) is not None:
        return None, "generation_already_present", local

    try:
        active, rolled = generation_state()
        active = int(active or 0)
    except Exception:
        return None, "generation_state_unavailable", local
    if not bool(rolled) or active <= 0:
        return None, "rollover_not_active", local

    try:
        manager = canonical_manager()
    except Exception:
        manager = None
    coordinator = getattr(manager, "_capital_coordinator", None) if manager is not None else None
    if coordinator is None:
        return None, "canonical_coordinator_missing", local

    worker = getattr(coordinator, "_nija_v142_flight_thread", None)
    if worker is not threading.current_thread():
        return None, "not_current_canonical_worker", local
    if not bool(getattr(coordinator, "_in_flight", False)):
        return None, "canonical_worker_not_in_flight", local
    if bool(getattr(coordinator, "_nija_v142_flight_timed_out", False)):
        return None, "canonical_worker_timed_out", local

    try:
        generation = int(getattr(coordinator, "_nija_v142_flight_generation", 0) or 0)
    except (TypeError, ValueError):
        generation = 0
    if generation <= 0:
        return None, "canonical_generation_missing", local
    if generation != active:
        return None, f"canonical_generation_not_active:{generation}!={active}", local
    return generation, "current_canonical_worker", local


def _patch_publication_context() -> bool:
    """Wrap CapitalAuthority publication and restore only proven v142 context."""
    try:
        v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
        ensure_fence = getattr(v142, "_patch_publication_generation_fence", None)
        if not callable(ensure_fence) or not bool(ensure_fence()):
            return False
        ca = importlib.import_module("bot.capital_authority")
        cls = getattr(ca, "CapitalAuthority", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if (
        str(getattr(current, "__name__", "")) == "publish_snapshot_v181"
        and bool(getattr(current, _PATCH_ATTR, False))
    ):
        return True

    v142_wrapper = _find_v142_publication_wrapper(current)
    if not callable(v142_wrapper):
        return False
    original = current

    @wraps(original)
    def publish_snapshot_v181(self: Any, snapshot: Any, writer_id: str) -> bool:
        authorized = str(writer_id or "") == str(
            getattr(self, "_AUTHORIZED_WRITER_ID", "mabm_capital_refresh_coordinator")
        )
        if not authorized:
            return bool(original(self, snapshot, writer_id))

        generation, reason, local = _canonical_generation_from_v142_wrapper(v142_wrapper)
        if generation is None or local is None:
            return bool(original(self, snapshot, writer_id))

        previous = getattr(local, "refresh_generation", _MISSING)
        setattr(local, "refresh_generation", generation)
        LOGGER.critical(
            "CAPITAL_V181_CANONICAL_WORKER_GENERATION_RESTORED marker=%s generation=%d "
            "reason=%s canonical_worker_only=true retired_workers_rejected=true "
            "publication_expiry_extended=false freshness_extended=false safety_gates_bypassed=false",
            MARKER,
            generation,
            reason,
        )
        try:
            return bool(original(self, snapshot, writer_id))
        finally:
            if previous is _MISSING:
                try:
                    delattr(local, "refresh_generation")
                except AttributeError:
                    pass
            else:
                setattr(local, "refresh_generation", previous)

    publish_snapshot_v181.__name__ = "publish_snapshot_v181"
    setattr(publish_snapshot_v181, _PATCH_ATTR, True)
    setattr(publish_snapshot_v181, "__wrapped__", original)
    cls.publish_snapshot = publish_snapshot_v181
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_generation_context_v181"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        publication_ok = _patch_publication_context()
        manifest_ok = _patch_release_manifest()
        ready = bool(publication_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_GENERATION_CONTEXT_V181_FAILED marker=%s publication_ok=%s "
                "manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(publication_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_CAPITAL_GENERATION_CONTEXT_V181 marker=%s ready=true "
            "canonical_worker_generation_recovery=true retired_worker_fence_preserved=true "
            "unknown_worker_fence_preserved=true freshness_extended=false "
            "publication_expiry_extended=false forced_trade=false safety_gates_bypassed=false",
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
    "_find_v142_publication_wrapper",
    "_canonical_generation_from_v142_wrapper",
    "_patch_publication_context",
    "_patch_release_manifest",
]
