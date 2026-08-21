"""Runtime bootstrap capital-publication convergence v179.

Production 2026-08-21 exposed a post-rollover bootstrap split:

* v142 correctly fences retired capital-coordinator generations, but the MABM
  minimal bootstrap seed is intentionally published outside the coordinator and
  therefore carries no v142 thread-local generation. Once any rollover has
  occurred, v142 treats that otherwise-authorized bootstrap seed as an unknown
  late publication and rejects it forever.
* CapitalAuthority can already be genuinely hydrated by a live direct refresh
  while the startup hydration helper is still observing a detached/unset event
  reference. The authority then reports real complete capital while bootstrap
  waits for an event whose invariant should already be true.

v179 repairs only those identity/invariant gaps. It never fabricates capital,
extends freshness, accepts a retired generation, clears a kill switch, grants
writer/nonce/execution authority, advances bootstrap directly, or forces a
trade.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_bootstrap_capital_publication_v179")
MARKER = "20260821-runtime-bootstrap-capital-publication-v179"
RELEASE_ID = "20260821-runtime-convergence-v179"
_READY_FLAG = "NIJA_RUNTIME_BOOTSTRAP_CAPITAL_PUBLICATION_V179_READY"
_PATCH_ATTR = "_nija_runtime_bootstrap_capital_publication_v179"
_SEED_PATCH_ATTR = "_nija_runtime_bootstrap_seed_v179"
_REFRESH_PATCH_ATTR = "_nija_runtime_hydration_invariant_v179"
_LOCK = threading.RLock()
_SEED_LOCK = threading.RLock()
_SEED_IDS: dict[int, float] = {}
_SEED_TTL_S = 60.0


def _canonical_ca_module():
    return importlib.import_module("bot.capital_authority")


def _v142_module():
    module = importlib.import_module("bot.capital_publication_liveness_v142_patch")
    installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
    if callable(installer):
        installer()
    return module


def _authority_hydrated(authority: Any) -> bool:
    value = getattr(authority, "is_hydrated", False)
    if callable(value):
        try:
            value = value()
        except Exception:
            return False
    return bool(value)


def _canonical_hydrated_event(*, repair: bool) -> threading.Event:
    module = _canonical_ca_module()
    event = getattr(module, "CAPITAL_HYDRATED_EVENT", None)
    if not isinstance(event, threading.Event):
        raise RuntimeError("canonical_hydrated_event_missing")
    if repair and not event.is_set():
        getter = getattr(module, "get_capital_authority", None)
        authority = getter() if callable(getter) else None
        if authority is not None and _authority_hydrated(authority):
            event.set()
            LOGGER.critical(
                "CAPITAL_V179_HYDRATION_EVENT_REPAIRED marker=%s "
                "authority_hydrated=true event_invariant_restored=true "
                "capital_mutated=false bootstrap_advanced=false safety_gates_bypassed=false",
                MARKER,
            )
    return event


def _canonical_system_ready_event() -> threading.Event:
    event = getattr(_canonical_ca_module(), "CAPITAL_SYSTEM_READY", None)
    if not isinstance(event, threading.Event):
        raise RuntimeError("canonical_system_ready_event_missing")
    return event


def _canonical_startup_lock() -> threading.Event:
    event = getattr(_canonical_ca_module(), "STARTUP_LOCK", None)
    if not isinstance(event, threading.Event):
        raise RuntimeError("canonical_startup_lock_missing")
    return event


def _prune_seed_ids(now: float | None = None) -> None:
    current = time.monotonic() if now is None else float(now)
    expired = [key for key, ts in _SEED_IDS.items() if current - ts > _SEED_TTL_S]
    for key in expired:
        _SEED_IDS.pop(key, None)


def _mark_bootstrap_seed(snapshot: Any) -> Any:
    if snapshot is None:
        return snapshot
    with _SEED_LOCK:
        _prune_seed_ids()
        _SEED_IDS[id(snapshot)] = time.monotonic()
    return snapshot


def _is_marked_bootstrap_seed(snapshot: Any) -> bool:
    if snapshot is None:
        return False
    with _SEED_LOCK:
        _prune_seed_ids()
        return id(snapshot) in _SEED_IDS


def _forget_bootstrap_seed(snapshot: Any) -> None:
    if snapshot is None:
        return
    with _SEED_LOCK:
        _SEED_IDS.pop(id(snapshot), None)


def _patch_mabm_seed() -> bool:
    module = importlib.import_module("bot.multi_account_broker_manager")
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_force_minimal_capital_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _SEED_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def seed_v179(self: Any, *args: Any, **kwargs: Any):
        return _mark_bootstrap_seed(original(self, *args, **kwargs))

    setattr(seed_v179, _SEED_PATCH_ATTR, True)
    setattr(seed_v179, "__wrapped__", original)
    cls._force_minimal_capital_snapshot = seed_v179
    return True


def _patch_capital_publish_seed_context() -> bool:
    module = _canonical_ca_module()
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    v142 = _v142_module()
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def publish_v179(self: Any, snapshot: Any, writer_id: str) -> bool:
        authorized = str(writer_id or "") == str(
            getattr(self, "_AUTHORIZED_WRITER_ID", "mabm_capital_refresh_coordinator")
        )
        marked_seed = _is_marked_bootstrap_seed(snapshot)
        local = getattr(v142, "_LOCAL", None)
        state = getattr(v142, "_generation_state", None)
        if not (authorized and marked_seed and local is not None and callable(state)):
            return bool(original(self, snapshot, writer_id=writer_id))

        active, rolled = state()
        prior = getattr(local, "refresh_generation", None)
        if prior is not None or not bool(rolled) or int(active or 0) <= 0:
            try:
                return bool(original(self, snapshot, writer_id=writer_id))
            finally:
                _forget_bootstrap_seed(snapshot)

        local.refresh_generation = int(active)
        try:
            accepted = bool(original(self, snapshot, writer_id=writer_id))
        finally:
            try:
                delattr(local, "refresh_generation")
            except AttributeError:
                pass
            _forget_bootstrap_seed(snapshot)

        LOGGER.critical(
            "CAPITAL_V179_BOOTSTRAP_SEED_GENERATION_CONTEXT marker=%s generation=%d "
            "accepted=%s exact_mabm_seed=true authorized_writer=true retired_generation_accepted=false "
            "freshness_extended=false capital_mutated=false safety_gates_bypassed=false",
            MARKER,
            int(active),
            str(accepted).lower(),
        )
        return accepted

    setattr(publish_v179, _PATCH_ATTR, True)
    setattr(publish_v179, "__wrapped__", original)
    cls.publish_snapshot = publish_v179
    return True


def _patch_capital_refresh_hydration_invariant() -> bool:
    module = _canonical_ca_module()
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "refresh", None)
    if not callable(current):
        return False
    if bool(getattr(current, _REFRESH_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def refresh_v179(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        if _authority_hydrated(self):
            _canonical_hydrated_event(repair=True)
        return result

    setattr(refresh_v179, _REFRESH_PATCH_ATTR, True)
    setattr(refresh_v179, "__wrapped__", original)
    cls.refresh = refresh_v179
    return True


def _patch_no_failure_hydration_readers() -> bool:
    module = importlib.import_module("bot.no_failure_activation_contract")

    def hydrated_event_v179() -> threading.Event:
        return _canonical_hydrated_event(repair=True)

    def system_ready_v179() -> threading.Event:
        return _canonical_system_ready_event()

    def startup_lock_v179() -> threading.Event:
        return _canonical_startup_lock()

    setattr(hydrated_event_v179, _PATCH_ATTR, True)
    setattr(system_ready_v179, _PATCH_ATTR, True)
    setattr(startup_lock_v179, _PATCH_ATTR, True)
    module._get_capital_hydrated_event = hydrated_event_v179
    module._get_capital_system_ready = system_ready_v179
    module._get_startup_lock = startup_lock_v179
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_bootstrap_capital_publication_v179"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            v142 = _v142_module()
            v142_ready = bool(v142)
            seed_ok = _patch_mabm_seed()
            publish_ok = _patch_capital_publish_seed_context()
            refresh_ok = _patch_capital_refresh_hydration_invariant()
            hydration_ok = _patch_no_failure_hydration_readers()
            manifest_ok = _patch_release_manifest()
            ready = bool(
                v142_ready
                and seed_ok
                and publish_ok
                and refresh_ok
                and hydration_ok
                and manifest_ok
            )
        except Exception as exc:
            LOGGER.critical(
                "RUNTIME_BOOTSTRAP_CAPITAL_PUBLICATION_V179_INSTALL_ERROR marker=%s error=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ready = False
            seed_ok = publish_ok = refresh_ok = hydration_ok = manifest_ok = False

        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_BOOTSTRAP_CAPITAL_PUBLICATION_V179_FAILED marker=%s seed_ok=%s "
                "publish_ok=%s refresh_ok=%s hydration_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(seed_ok).lower(),
                str(publish_ok).lower(),
                str(refresh_ok).lower(),
                str(hydration_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        LOGGER.critical(
            "RUNTIME_BOOTSTRAP_CAPITAL_PUBLICATION_V179 marker=%s ready=true "
            "mabm_seed_generation_context=true canonical_hydration_event=true "
            "authority_hydration_invariant=true retired_generation_fence_preserved=true "
            "freshness_ttl_unchanged=true capital_mutated=false kill_switch_unchanged=true "
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
    "_mark_bootstrap_seed",
    "_is_marked_bootstrap_seed",
    "_patch_mabm_seed",
    "_patch_capital_publish_seed_context",
    "_patch_capital_refresh_hydration_invariant",
    "_patch_no_failure_hydration_readers",
]
