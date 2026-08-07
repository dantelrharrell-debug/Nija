"""Separate Kraken nonce-lease generations from process writer authority.

The process writer lock and per-key Kraken nonce leases are distinct fencing
systems.  They must never share a Redis generation counter or publish into the
same environment variables.

Process writer authority is owned exclusively by EntrypointWriterAuthority:
- Redis generation key: NIJA_LEASE_GENERATION_KEY (default nija:lease:generation)
- Env generation: NIJA_WRITER_LEASE_GENERATION / NIJA_WRITER_GENERATION
- Fencing token: NIJA_WRITER_FENCING_TOKEN

Kraken nonce leases use their own generation domain:
- Redis generation key: NIJA_KRAKEN_NONCE_LEASE_GENERATION_KEY
  (default nija:kraken:writer:generation)
- Platform telemetry env: NIJA_PLATFORM_NONCE_LEASE_GENERATION

This compatibility patch is installed before nonce-manager construction on the
canonical production path.  It never grants process writer authority and never
copies a nonce lease version into process-writer lineage.
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import os
import threading
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.writer_generation_scope_repair")
MARKER = "20260807-writer-generation-domain-v2"
_LOCK = threading.RLock()
_LEASE_SCOPE = threading.local()
_INSTALLED = False
_LAST_PLATFORM_NONCE_GENERATION: int | None = None

_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_PROCESS_GENERATION_REDIS_KEY_DEFAULT = "nija:lease:generation"
_NONCE_GENERATION_REDIS_KEY_DEFAULT = "nija:kraken:writer:generation"


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _platform_api_key() -> str:
    return (
        str(os.environ.get("KRAKEN_PLATFORM_API_KEY", "") or "").strip()
        or str(os.environ.get("KRAKEN_API_KEY", "") or "").strip()
    )


def _platform_key_id() -> str:
    raw = _platform_api_key()
    return hashlib.sha256(raw.encode()).hexdigest()[:16] if raw else ""


def _process_generation_key() -> str:
    return (
        str(os.environ.get("NIJA_LEASE_GENERATION_KEY", "") or "").strip()
        or _PROCESS_GENERATION_REDIS_KEY_DEFAULT
    )


def _nonce_generation_key() -> str:
    requested = (
        str(os.environ.get("NIJA_KRAKEN_NONCE_LEASE_GENERATION_KEY", "") or "").strip()
        or _NONCE_GENERATION_REDIS_KEY_DEFAULT
    )
    process_key = _process_generation_key()
    if requested == process_key:
        logger.critical(
            "NONCE_GENERATION_DOMAIN_COLLISION_REJECTED marker=%s requested=%s process_key=%s fallback=%s",
            MARKER,
            requested,
            process_key,
            _NONCE_GENERATION_REDIS_KEY_DEFAULT,
        )
        requested = _NONCE_GENERATION_REDIS_KEY_DEFAULT
    os.environ["NIJA_KRAKEN_NONCE_LEASE_GENERATION_KEY"] = requested
    return requested


def _process_writer_established() -> bool:
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    return bool(_truthy("NIJA_WRITER_LEASE_ACQUIRED") and generation and token)


def _process_writer_snapshot() -> tuple[str, str, str, str]:
    return (
        str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or ""),
        str(os.environ.get("NIJA_WRITER_LEASE_GENERATION_LAST", "") or ""),
        str(os.environ.get("NIJA_WRITER_GENERATION", "") or ""),
        str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or ""),
    )


def _restore_nonce_pollution_if_detected(
    before: tuple[str, str, str, str],
    lease_version: int,
) -> None:
    """Repair only a provable nonce overwrite without clobbering real re-election.

    The replacement publisher below prevents the overwrite in normal operation.
    This guard exists for copied/legacy backend wrappers.  It restores the prior
    writer generation only when the fencing token is unchanged and the current
    generation equals the nonce lease version that just returned.
    """
    before_gen, before_last, before_alias, before_token = before
    after_token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "")
    after_gen = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "")
    if not before_gen or not before_token or after_token != before_token:
        return
    if after_gen != str(int(lease_version)) or after_gen == before_gen:
        return
    os.environ["NIJA_WRITER_LEASE_GENERATION"] = before_gen
    if before_last:
        os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = before_last
    else:
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION_LAST", None)
    if before_alias:
        os.environ["NIJA_WRITER_GENERATION"] = before_alias
    else:
        os.environ.pop("NIJA_WRITER_GENERATION", None)
    logger.critical(
        "NONCE_GENERATION_PROCESS_WRITER_POLLUTION_REPAIRED marker=%s nonce_generation=%s restored_writer_generation=%s",
        MARKER,
        lease_version,
        before_gen,
    )


def _publish_nonce_generation(key_id: str, lease_version: int) -> None:
    global _LAST_PLATFORM_NONCE_GENERATION
    os.environ["NIJA_NONCE_LEASE_ACQUIRED"] = "1"
    os.environ["NIJA_NONCE_LEASE_GENERATION_KEY"] = _nonce_generation_key()
    platform_id = _platform_key_id()
    if platform_id and str(key_id) == platform_id:
        os.environ["NIJA_PLATFORM_NONCE_LEASE_GENERATION"] = str(int(lease_version))
        if _LAST_PLATFORM_NONCE_GENERATION != int(lease_version):
            _LAST_PLATFORM_NONCE_GENERATION = int(lease_version)
            logger.info(
                "PLATFORM_NONCE_GENERATION_PUBLISHED marker=%s key_id=%s nonce_generation=%d process_writer_generation=%s",
                MARKER,
                key_id,
                int(lease_version),
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", "unset"),
            )


def _advance_bootstrap_after_nonce_lease() -> None:
    """Preserve the legacy bootstrap handoff only after process authority exists."""
    if not _process_writer_established():
        logger.warning(
            "NONCE_LEASE_BOOTSTRAP_HANDOFF_DEFERRED marker=%s reason=process_writer_not_established",
            MARKER,
        )
        return
    try:
        bootstrap_state = None
        bootstrap_enum = None
        for module_name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
            try:
                module = importlib.import_module(module_name)
                bootstrap_state = getattr(module, "get_bootstrap_fsm", lambda: None)()
                bootstrap_enum = getattr(module, "BootstrapState", None)
                if bootstrap_state is not None:
                    break
            except Exception:
                continue
        if bootstrap_state is None:
            return
        current_state = getattr(getattr(bootstrap_state, "state", None), "value", None)
        if current_state is None:
            current_state = getattr(bootstrap_state, "current_state", None)
            current_state = getattr(current_state, "value", current_state)
        if str(current_state) != "BOOT_INIT":
            return
        target = (
            getattr(bootstrap_enum, "LOCK_ACQUIRED", None)
            if bootstrap_enum is not None
            else "LOCK_ACQUIRED"
        )
        transition = getattr(bootstrap_state, "transition", None)
        if callable(transition):
            try:
                transition(target, reason="redis_nonce_lease_acquired_after_process_writer")
            except TypeError:
                transition(target, "redis_nonce_lease_acquired_after_process_writer")
            logger.critical(
                "[BOOTSTRAP FSM] BOOT_INIT -> LOCK_ACQUIRED reason=redis_nonce_lease_acquired_after_process_writer"
            )
    except Exception as exc:
        logger.warning(
            "NONCE_LEASE_BOOTSTRAP_HANDOFF_FAILED marker=%s err=%s",
            MARKER,
            exc,
        )


def _patch_nonce_backend(module: ModuleType) -> bool:
    backend = getattr(module, "_PerKeyRedisBackend", None)
    if not isinstance(backend, type):
        return False

    # Separate the Redis counters before any lease script executes.  The Lua
    # scripts receive this key at call time, so this also fixes existing backend
    # instances that have not yet acquired/renewed a lease.
    setattr(backend, "_LEASE_GENERATION_KEY", _nonce_generation_key())

    publish_current = getattr(backend, "_publish_lock_acquired_state", None)
    if callable(publish_current) and not getattr(
        publish_current, "_nija_nonce_generation_domain_v2", False
    ):
        def _publish_lock_acquired_state(self: Any, lease_version: int) -> None:
            key_id = str(getattr(_LEASE_SCOPE, "key_id", "") or "")
            _publish_nonce_generation(key_id, int(lease_version))
            _advance_bootstrap_after_nonce_lease()

        _publish_lock_acquired_state._nija_nonce_generation_domain_v2 = True  # type: ignore[attr-defined]
        _publish_lock_acquired_state.__wrapped__ = publish_current  # type: ignore[attr-defined]
        setattr(backend, "_publish_lock_acquired_state", _publish_lock_acquired_state)

    ensure_current = getattr(backend, "_ensure_writer_lease", None)
    if not callable(ensure_current):
        return False
    if getattr(ensure_current, "_nija_nonce_generation_domain_v2", False):
        return True

    def _ensure_writer_lease(self: Any, key_id: str, *args: Any, **kwargs: Any) -> int:
        before = _process_writer_snapshot()
        previous_key_id = getattr(_LEASE_SCOPE, "key_id", None)
        _LEASE_SCOPE.key_id = str(key_id)
        try:
            # Re-assert the separated key in case another compatibility layer
            # modified the class/instance attribute after installation.
            setattr(self, "_LEASE_GENERATION_KEY", _nonce_generation_key())
            version = int(ensure_current(self, key_id, *args, **kwargs))
        finally:
            if previous_key_id is None:
                try:
                    delattr(_LEASE_SCOPE, "key_id")
                except AttributeError:
                    pass
            else:
                _LEASE_SCOPE.key_id = previous_key_id
        _restore_nonce_pollution_if_detected(before, version)
        _publish_nonce_generation(str(key_id), version)
        return version

    _ensure_writer_lease._nija_nonce_generation_domain_v2 = True  # type: ignore[attr-defined]
    _ensure_writer_lease.__wrapped__ = ensure_current  # type: ignore[attr-defined]
    setattr(backend, "_ensure_writer_lease", _ensure_writer_lease)
    logger.warning(
        "NONCE_WRITER_GENERATION_DOMAIN_SEPARATED marker=%s nonce_key=%s process_key=%s",
        MARKER,
        _nonce_generation_key(),
        _process_generation_key(),
    )
    return True


def _patch_generation_tracker(module: ModuleType) -> bool:
    """Compatibility no-op: process writer tracker must remain process-scoped."""
    getter = getattr(module, "get_redis_generation", None)
    if not callable(getter):
        return False
    if not getattr(getter, "_nija_process_writer_generation_domain_v2", False):
        try:
            setattr(getter, "_nija_process_writer_generation_domain_v2", True)
        except Exception:
            pass
        logger.warning(
            "PROCESS_WRITER_GENERATION_TRACKER_PRESERVED marker=%s process_key=%s",
            MARKER,
            _process_generation_key(),
        )
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        try:
            from bot import distributed_nonce_manager as nonce_module
            from bot import writer_generation_tracker as tracker_module
        except ImportError:
            import distributed_nonce_manager as nonce_module  # type: ignore[no-redef]
            import writer_generation_tracker as tracker_module  # type: ignore[no-redef]

        nonce_ok = _patch_nonce_backend(nonce_module)
        tracker_ok = _patch_generation_tracker(tracker_module)
        _INSTALLED = bool(nonce_ok and tracker_ok)
        if not _INSTALLED:
            raise RuntimeError("writer generation domain separation did not attach")
        os.environ["NIJA_WRITER_GENERATION_SCOPE_REPAIR_INSTALLED"] = "1"
        os.environ["NIJA_WRITER_GENERATION_DOMAIN_SEPARATED"] = "1"
        logger.warning(
            "WRITER_GENERATION_SCOPE_REPAIR_INSTALLED marker=%s nonce_key=%s process_key=%s",
            MARKER,
            _nonce_generation_key(),
            _process_generation_key(),
        )
        return True


def installed() -> bool:
    return _INSTALLED


__all__ = [
    "install",
    "installed",
    "_platform_key_id",
    "_nonce_generation_key",
    "_process_generation_key",
    "_patch_nonce_backend",
    "_patch_generation_tracker",
]
