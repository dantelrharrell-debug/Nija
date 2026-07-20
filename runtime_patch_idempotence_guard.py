"""Prevent legacy runtime watchdogs from reinstalling a second scan owner."""
from __future__ import annotations

import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_patch_idempotence")
_MARKER = "20260719-runtime-patch-idempotence-v1"
_CANONICAL_RELEASE = "20260714a"
_LOCK = threading.RLock()
_STARTED = False


def _guard_module(module: ModuleType) -> bool:
    current = getattr(module, "_patch_core_loop", None)
    if not callable(current) or getattr(current, "_nija_canonical_owner_defer_v1", False):
        return False
    original: Callable[..., Any] = current

    def guarded(target: ModuleType) -> bool:
        cls = getattr(target, "NijaCoreLoop", None)
        method = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
        if callable(method) and (
            getattr(method, "_nija_scan_wrapper_release", "") == _CANONICAL_RELEASE
            or getattr(method, "_nija_scan_wrapper_canonical_v2", False)
        ):
            return False
        return bool(original(target))

    guarded._nija_canonical_owner_defer_v1 = True  # type: ignore[attr-defined]
    guarded.__wrapped__ = original  # type: ignore[attr-defined]
    module._patch_core_loop = guarded
    logger.critical("LEGACY_SCAN_OWNER_DEFERRED marker=%s module=%s canonical=%s", _MARKER, module.__name__, _CANONICAL_RELEASE)
    return True


def _watch() -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        for name in ("runtime_convergence_v2_patch", "nija.runtime_convergence_v2_patch"):
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                _guard_module(module)
        time.sleep(0.25)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return True
        _STARTED = True
        threading.Thread(target=_watch, name="RuntimePatchIdempotence", daemon=True).start()
        logger.warning("RUNTIME_PATCH_IDEMPOTENCE_INSTALLED marker=%s", _MARKER)
        return True


install()
