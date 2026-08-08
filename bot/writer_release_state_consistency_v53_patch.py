"""Writer release-state consistency v53.

Production on the v52 build exposed a local/distributed writer split after an
explicit EntrypointWriterAuthority.release(): Redis and writer environment state
were cleared, but the singleton could still report ``acquired=True`` because
``release()`` did not set its internal ``_lost`` event. The release path also
left process-level execution-authority claims untouched.

That stale local acquisition can poison fresh-epoch recovery: a subsequent
``acquire_once()`` may return the previous successful result without touching
Redis, while heartbeat/readiness correctly observe generation 0 and no
canonical authority.

v53 wraps only the canonical release method. Before any release-side Redis
mutation it invalidates local acquisition and process execution claims. The
existing release implementation still owns heartbeat quiescing and
compare-and-delete semantics. Intentional release does not invoke the on-lost
callback, does not halt SEAK, and does not fabricate or reacquire authority.
A future acquire must pass through the normal Redis election path, where the
canonical activation code clears ``_lost`` only after a new lease succeeds.
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

LOGGER = logging.getLogger("nija.writer_release_state_consistency_v53")
MARKER = "20260808-writer-release-state-v53"

_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_writer_release_state_v53"
_INSTALL_FLAG = "_NIJA_WRITER_RELEASE_STATE_V53_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_RELEASE_STATE_V53_IMPORTLIB_HOOK"
_TARGETS = {"bot.entrypoint_writer_authority", "entrypoint_writer_authority"}


def _invalidate_local_release_state(runtime: Any) -> None:
    lost = getattr(runtime, "_lost", None)
    setter = getattr(lost, "set", None)
    if callable(setter):
        setter()
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    os.environ["NIJA_WRITER_RELEASE_STATE_V53_INVALIDATED"] = "1"


def _patch_entrypoint_writer_authority(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "release", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    @wraps(original)
    def release(self: Any, *args: Any, **kwargs: Any):
        # Invalidate local authority before heartbeat shutdown / Redis deletion,
        # so no concurrent reader can observe an intentionally released writer
        # as still acquired. Do not call _mark_lost(): intentional release must
        # not invoke loss callbacks or SEAK emergency-halt semantics.
        _invalidate_local_release_state(self)
        result = original(self, *args, **kwargs)
        # Preserve fail-closed state even if a legacy release wrapper mutates
        # environment variables after the canonical release returns.
        _invalidate_local_release_state(self)
        LOGGER.critical(
            "WRITER_RELEASE_STATE_V53_INVALIDATED marker=%s acquired=%s lost=%s "
            "execution_authority=0 execution_active=false reacquire_requires_redis=true",
            MARKER,
            str(bool(getattr(self, "acquired", False))).lower(),
            str(bool(getattr(self, "lost", False))).lower(),
        )
        return result

    setattr(release, _PATCH_ATTR, True)
    setattr(release, "__wrapped__", original)
    cls.release = release
    LOGGER.critical(
        "WRITER_RELEASE_STATE_V53_PATCHED marker=%s module=%s "
        "intentional_release_callback=false redis_semantics=delegated",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        changed = _patch_entrypoint_writer_authority(module) or changed
    return changed


def _interesting(name: str) -> bool:
    return str(name or "") in _TARGETS


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()

        if not getattr(builtins, _INSTALL_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(
                name: str,
                globals: Any = None,
                locals: Any = None,
                fromlist: Any = (),
                level: int = 0,
            ):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _INSTALL_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if _interesting(name):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_WRITER_RELEASE_STATE_V53_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_RELEASE_STATE_V53_INSTALLED marker=%s fail_closed=true "
            "lock_acquire=false lock_extend=false lock_delete=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_invalidate_local_release_state",
    "_patch_entrypoint_writer_authority",
]
