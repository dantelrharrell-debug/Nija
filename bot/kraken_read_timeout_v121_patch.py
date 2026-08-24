"""Bound read-only Kraken HTTP calls and the global API-lock wait.

Production generation logs showed repeated v117 Kraken position generations
reaching the 12-second caller timeout. NIJA's Kraken private-call wrapper holds
the process-wide Kraken API lock while calling ``krakenex.API.query_private``.
v121 already bounds the HTTP request itself, but production on 2026-08-24 proved
a second liveness gap: a read-only caller can wait indefinitely *before* the
HTTP timeout begins while another caller owns the global lock. Heartbeat v210
then times out its outer caller while the underlying daemon remains blocked on
the lock, causing every later heartbeat retry to see the same in-flight worker.

This hardening bounds only acquisition of the existing process-wide Kraken API
lock for read-only private calls. Mutating methods (AddOrder/Cancel/Edit/etc.)
preserve their existing serialization and timeout semantics so an ambiguous
client timeout cannot trigger an automatic duplicate mutation. Once the read
lock is acquired, the existing method runs unchanged and re-enters the same
``RLock``; HTTP read timeouts remain owned by v121. Public reads are unchanged.
v117 remains the outer fail-closed position snapshot authority and synthetic
empty snapshots remain forbidden.

No new builtins/importlib hook is installed. Future broker_manager imports are
patched by extending v117's already-installed broker-manager dispatch hook.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.kraken_read_timeout_v121")
MARKER = "20260816-kraken-read-timeout-v121"
LOCK_BOUND_MARKER = "20260824-kraken-read-lock-bound-v212"
RELEASE_ID = "20260816-runtime-convergence-v121"
_PATCH_ATTR = "_nija_kraken_read_timeout_v121"
_API_ATTR = "_nija_kraken_read_timeout_v121_api"
_V117_DISPATCH_ATTR = "_nija_kraken_read_timeout_v121_dispatch"
_LOCK = threading.RLock()
_INSTALLED = False

_MUTATING = {
    "AddOrder",
    "AddOrderBatch",
    "CancelOrder",
    "CancelOrderBatch",
    "CancelAll",
    "CancelAllOrdersAfter",
    "EditOrder",
}


class KrakenReadLockBusy(RuntimeError):
    """Fail-closed signal that a read could not enter the Kraken API lock."""


def _env_timeout(name: str, default: float, *, maximum: float = 30.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(1.0, min(maximum, value))


def _private_read_timeout_s() -> float:
    return _env_timeout("NIJA_KRAKEN_PRIVATE_READ_TIMEOUT_S", 8.0)


def _public_read_timeout_s() -> float:
    return _env_timeout("NIJA_KRAKEN_PUBLIC_READ_TIMEOUT_S", 6.0)


def _private_read_lock_wait_s() -> float:
    # Keep lock admission + the default 8 s HTTP read bound inside the
    # heartbeat v210 12 s outer budget under normal configuration.
    return _env_timeout("NIJA_KRAKEN_PRIVATE_READ_LOCK_WAIT_S", 3.0, maximum=10.0)


def _wrap_api(api: Any) -> bool:
    if api is None:
        return True
    if bool(getattr(api, _API_ATTR, False)):
        return True

    original_private = getattr(api, "query_private", None)
    original_public = getattr(api, "query_public", None)
    if not callable(original_private):
        return False

    @wraps(original_private)
    def query_private(method: str, data: Any = None, timeout: Any = None):
        selected = timeout
        read_only = str(method or "") not in _MUTATING
        if selected is None and read_only:
            selected = _private_read_timeout_s()
        if selected is not None and read_only:
            LOGGER.debug(
                "KRAKEN_READ_TIMEOUT_V121_PRIVATE method=%s timeout_s=%.2f read_only=true",
                method,
                float(selected),
            )
        return original_private(method, data, timeout=selected)

    api.query_private = query_private

    if callable(original_public):
        @wraps(original_public)
        def query_public(method: str, data: Any = None, timeout: Any = None):
            selected = timeout if timeout is not None else _public_read_timeout_s()
            return original_public(method, data, timeout=selected)

        api.query_public = query_public

    setattr(api, _API_ATTR, True)
    LOGGER.critical(
        "KRAKEN_READ_TIMEOUT_V121_API_PATCHED marker=%s private_read_timeout_s=%.2f public_read_timeout_s=%.2f mutating_timeout_semantics_unchanged=true",
        MARKER,
        _private_read_timeout_s(),
        _public_read_timeout_s(),
    )
    return True


def _method_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if args:
        return str(args[0] or "")
    return str(kwargs.get("method") or "")


def _acquire_global_read_lock(module: ModuleType, method: str) -> tuple[Any | None, bool]:
    """Bound read-only admission to the canonical Kraken global RLock.

    Returning ``(None, False)`` means the canonical getter is unavailable and
    the existing broker method should run unchanged. A busy canonical lock
    raises ``KrakenReadLockBusy`` so the caller fails closed without leaving a
    daemon parked indefinitely behind another Kraken request.
    """
    if method in _MUTATING:
        return None, False

    getter = getattr(module, "get_kraken_api_lock", None)
    if not callable(getter):
        return None, False

    try:
        global_lock = getter()
    except Exception:
        # Preserve the broker's existing error behavior if its canonical lock
        # getter itself is unavailable/broken.
        return None, False

    acquire = getattr(global_lock, "acquire", None)
    release = getattr(global_lock, "release", None)
    if not callable(acquire) or not callable(release):
        return None, False

    wait_s = _private_read_lock_wait_s()
    try:
        acquired = bool(acquire(timeout=wait_s))
    except TypeError:
        acquired = bool(acquire(True, wait_s))

    if not acquired:
        LOGGER.warning(
            "KRAKEN_READ_LOCK_V212_BUSY marker=%s method=%s wait_s=%.2f "
            "read_only=true action=fail_closed_retry global_lock_preserved=true "
            "http_timeout_unchanged=true mutating_calls_unchanged=true",
            LOCK_BOUND_MARKER,
            method or "unknown",
            wait_s,
        )
        raise KrakenReadLockBusy(
            f"Kraken read lock busy after {wait_s:.2f}s for {method or 'private_read'}"
        )

    return global_lock, True


def _patch_broker_manager(module: ModuleType | None = None) -> bool:
    module = module or sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if not isinstance(module, ModuleType):
        return True

    cls = getattr(module, "KrakenBroker", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if not getattr(current, _PATCH_ATTR, False):
        @wraps(current)
        def kraken_private_call_v121(self: Any, *args: Any, **kwargs: Any):
            _wrap_api(getattr(self, "api", None))
            method = _method_from_call(args, kwargs)

            # Mutations deliberately keep the original lock wait and request
            # timeout semantics. Only read-only calls get bounded admission.
            if method in _MUTATING:
                return current(self, *args, **kwargs)

            global_lock, acquired = _acquire_global_read_lock(module, method)
            if not acquired or global_lock is None:
                return current(self, *args, **kwargs)

            try:
                # broker_manager._kraken_private_call re-enters this same
                # process-wide threading.RLock, so its existing serialization,
                # rate-limit, nonce, circuit-breaker, and fallback logic remain
                # unchanged once admission succeeds.
                return current(self, *args, **kwargs)
            finally:
                global_lock.release()

        setattr(kraken_private_call_v121, _PATCH_ATTR, True)
        setattr(kraken_private_call_v121, "__wrapped__", current)
        cls._kraken_private_call = kraken_private_call_v121

    iterator = getattr(cls, "_iter_live", None)
    if callable(iterator):
        try:
            for broker in list(iterator() or []):
                _wrap_api(getattr(broker, "api", None))
        except Exception:
            LOGGER.debug("KRAKEN_READ_TIMEOUT_V121 live-instance patch skipped", exc_info=True)

    LOGGER.critical(
        "KRAKEN_READ_TIMEOUT_V121_BROKER_PATCHED marker=%s lock_marker=%s broker_class=KrakenBroker "
        "private_read_timeout_s=%.2f public_read_timeout_s=%.2f private_read_lock_wait_s=%.2f "
        "read_lock_wait_bounded=true global_lock_preserved=true mutating_lock_wait_unchanged=true "
        "synthetic_empty_snapshot=false",
        MARKER,
        LOCK_BOUND_MARKER,
        _private_read_timeout_s(),
        _public_read_timeout_s(),
        _private_read_lock_wait_s(),
    )
    return True


def _patch_v117_dispatch() -> bool:
    try:
        from bot import position_fetch_generation_v117_patch as v117
    except Exception:
        return False

    current = getattr(v117, "_patch_broker_manager", None)
    if not callable(current):
        return False
    if getattr(current, _V117_DISPATCH_ATTR, False):
        return True

    @wraps(current)
    def patch_broker_manager_v121() -> bool:
        if not current():
            return False
        module = sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
        return _patch_broker_manager(module if isinstance(module, ModuleType) else None)

    setattr(patch_broker_manager_v121, _V117_DISPATCH_ATTR, True)
    setattr(patch_broker_manager_v121, "__wrapped__", current)
    v117._patch_broker_manager = patch_broker_manager_v121
    LOGGER.critical(
        "KRAKEN_READ_TIMEOUT_V121_V117_DISPATCH_PATCHED marker=%s existing_import_hook_reused=true new_import_hook=false",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        try:
            import bot.runtime_release_manifest_patch as manifest  # type: ignore[no-redef]
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["kraken_read_timeout_v121"] = "NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED"
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if not _patch_v117_dispatch():
            return False
        if not _patch_broker_manager():
            return False
        os.environ["NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED"] = "1"
        if not _patch_release_manifest():
            os.environ.pop("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", None)
            return False
        _INSTALLED = True
        LOGGER.critical(
            "KRAKEN_READ_TIMEOUT_V121_INSTALLED marker=%s lock_marker=%s private_read_timeout_s=%.2f "
            "public_read_timeout_s=%.2f private_read_lock_wait_s=%.2f read_lock_wait_bounded=true "
            "mutating_calls_unchanged=true import_hook_added=false execution_gates_unchanged=true",
            MARKER,
            LOCK_BOUND_MARKER,
            _private_read_timeout_s(),
            _public_read_timeout_s(),
            _private_read_lock_wait_s(),
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v121 deliberately adds no import hook."""
    return install()


__all__ = [
    "MARKER",
    "LOCK_BOUND_MARKER",
    "RELEASE_ID",
    "KrakenReadLockBusy",
    "install",
    "install_import_hook",
    "_private_read_lock_wait_s",
    "_wrap_api",
    "_patch_broker_manager",
    "_patch_v117_dispatch",
]
