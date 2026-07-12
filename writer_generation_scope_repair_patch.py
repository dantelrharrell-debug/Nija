"""Keep platform writer lineage isolated from user Kraken nonce leases.

Each Kraken API key owns an independent Redis nonce lease.  The legacy backend
published every per-key lease version into the process-wide
NIJA_WRITER_LEASE_GENERATION variable and validated it against one global Redis
counter.  Connecting user accounts therefore advanced the global counter and
made the platform writer appear stale even though its own lease was healthy.

This repair makes the platform key's per-key lease version authoritative for
process writer lineage and prevents user-key leases from mutating platform
writer-generation state.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.writer_generation_scope_repair")
MARKER = "20260712f"
_LOCK = threading.RLock()
_INSTALLED = False

_GENERATION_ENV_KEYS = (
    "NIJA_WRITER_LEASE_GENERATION",
    "NIJA_WRITER_LEASE_GENERATION_LAST",
    "NIJA_WRITER_LEASE_GENERATION_EXPECTED",
)


def _platform_api_key() -> str:
    return (
        str(os.environ.get("KRAKEN_PLATFORM_API_KEY", "") or "").strip()
        or str(os.environ.get("KRAKEN_API_KEY", "") or "").strip()
    )


def _platform_key_id() -> str:
    raw = _platform_api_key()
    return hashlib.sha256(raw.encode()).hexdigest()[:16] if raw else ""


def _snapshot_generation_env() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in _GENERATION_ENV_KEYS}


def _restore_generation_env(snapshot: dict[str, str | None]) -> None:
    for name, value in snapshot.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _patch_nonce_backend(module: ModuleType) -> bool:
    backend = getattr(module, "_PerKeyRedisBackend", None)
    if not isinstance(backend, type):
        return False
    original = getattr(backend, "_ensure_writer_lease", None)
    if not callable(original) or getattr(original, "_nija_platform_generation_scoped", False):
        return False

    def _ensure_writer_lease(self: Any, key_id: str, *args: Any, **kwargs: Any) -> int:
        platform_id = _platform_key_id()
        is_platform = bool(platform_id and str(key_id) == platform_id)
        before = _snapshot_generation_env()
        version = int(original(self, key_id, *args, **kwargs))
        if is_platform:
            os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(version)
            os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = str(version)
            logger.info(
                "PLATFORM_WRITER_GENERATION_PUBLISHED marker=%s key_id=%s generation=%d",
                MARKER, key_id, version,
            )
        else:
            _restore_generation_env(before)
            logger.debug(
                "USER_NONCE_LEASE_GENERATION_ISOLATED marker=%s key_id=%s lease_version=%d",
                MARKER, key_id, version,
            )
        return version

    _ensure_writer_lease._nija_platform_generation_scoped = True  # type: ignore[attr-defined]
    _ensure_writer_lease.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(backend, "_ensure_writer_lease", _ensure_writer_lease)
    logger.warning("NONCE_LEASE_GENERATION_SCOPE_PATCHED marker=%s", MARKER)
    return True


def _patch_generation_tracker(module: ModuleType) -> bool:
    original = getattr(module, "get_redis_generation", None)
    connector = getattr(module, "_connect_redis", None)
    if not callable(original) or not callable(connector):
        return False
    if getattr(original, "_nija_platform_generation_scoped", False):
        return False

    def get_redis_generation() -> tuple[int, str]:
        key_id = _platform_key_id()
        if not key_id:
            return 0, "platform_api_key_not_configured"
        client, err = connector(timeout_s=2)
        if client is None:
            return 0, err or "redis_unavailable"
        redis_key = f"nija:kraken:writer:lease_version:{key_id}"
        try:
            raw = client.get(redis_key)
            if raw is None:
                return 0, f"platform_lease_version_missing:{key_id}"
            return max(0, int(str(raw).strip())), ""
        except Exception as exc:
            return 0, f"platform_lease_version_read_error:{exc}"

    get_redis_generation._nija_platform_generation_scoped = True  # type: ignore[attr-defined]
    get_redis_generation.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(module, "get_redis_generation", get_redis_generation)
    logger.warning("WRITER_GENERATION_TRACKER_PLATFORM_SCOPED marker=%s", MARKER)
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
        already_nonce = bool(getattr(getattr(nonce_module, "_PerKeyRedisBackend", None), "_ensure_writer_lease", None) and getattr(getattr(nonce_module._PerKeyRedisBackend, "_ensure_writer_lease"), "_nija_platform_generation_scoped", False))
        already_tracker = bool(getattr(getattr(tracker_module, "get_redis_generation", None), "_nija_platform_generation_scoped", False))
        _INSTALLED = (nonce_ok or already_nonce) and (tracker_ok or already_tracker)
        if not _INSTALLED:
            raise RuntimeError("platform writer generation scope patch did not attach")
        os.environ["NIJA_WRITER_GENERATION_SCOPE_REPAIR_INSTALLED"] = "1"
        logger.warning("WRITER_GENERATION_SCOPE_REPAIR_INSTALLED marker=%s", MARKER)
        return True


def installed() -> bool:
    return _INSTALLED


__all__ = ["install", "installed", "_platform_key_id"]
