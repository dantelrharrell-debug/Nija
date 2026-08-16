"""Keep the canonical fast path behind NIJA's process-wide import compactor.

Production release v121 showed a very deep compatibility ``__import__`` wrapper
chain while sklearn/joblib was imported during a live runtime.  The repository
already ships ``import_hook_recursion_shield_patch`` to compact that chain, but
canonical production sets ``NIJA_DEFER_RUNTIME_SITE_HOOKS=1`` and therefore
skips the .pth installer that normally activates the shield.  The canonical
``bot.py`` fast path also did not install it explicitly.

v123 closes that lifecycle gap without removing historical safety wrappers:

* the existing compactor is installed before any canonical fast-path guard;
* the compactor's existing short-lived monitor remains intact;
* a lightweight daemon keeps re-compacting late wrapper replacements for the
  lifetime of the process after the historical 600-second monitor expires;
* the runtime release manifest eventually requires and attests v123;
* no writer, nonce, broker, capital, risk, position, kill-switch, strategy, or
  execution readiness is synthesized or bypassed.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.canonical_import_shield_v123")
MARKER = "20260816-canonical-import-shield-v123"
RELEASE_ID = "20260816-runtime-convergence-v123"
_FLAG = "NIJA_CANONICAL_IMPORT_SHIELD_V123_INSTALLED"
_MONITOR_ATTR = "_NIJA_CANONICAL_IMPORT_SHIELD_V123_MONITOR_STARTED"
_LOCK = threading.RLock()
_INSTALLED = False


def _load_shield() -> Any:
    import import_hook_recursion_shield_patch as shield

    return shield


def _shield_active() -> bool:
    current = builtins.__import__
    return bool(getattr(current, "_nija_import_chain_compactor", None))


def _patch_release_manifest_if_loaded() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["canonical_import_shield_v123"] = _FLAG
    manifest.RELEASE_ID = RELEASE_ID
    return True


def _lifetime_monitor(shield: Any) -> None:
    manifest_patched = False
    last_error_log = 0.0
    while True:
        try:
            compactor = getattr(shield, "compact_import_chain", None)
            if callable(compactor):
                compactor()
            if not manifest_patched:
                manifest_patched = _patch_release_manifest_if_loaded()
        except BaseException as exc:
            now = time.monotonic()
            if now - last_error_log >= 60.0:
                LOGGER.warning(
                    "CANONICAL_IMPORT_SHIELD_V123_MONITOR_ERROR marker=%s error=%s:%s fail_closed_gates_unchanged=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
                last_error_log = now
        time.sleep(0.5)


def _start_lifetime_monitor(shield: Any) -> bool:
    if bool(getattr(builtins, _MONITOR_ATTR, False)):
        return True
    setattr(builtins, _MONITOR_ATTR, True)
    try:
        thread = threading.Thread(
            target=_lifetime_monitor,
            args=(shield,),
            name="canonical-import-shield-v123",
            daemon=True,
        )
        thread.start()
    except BaseException:
        setattr(builtins, _MONITOR_ATTR, False)
        raise
    return bool(thread.is_alive())


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            shield = _load_shield()
            installer = getattr(shield, "install_import_hook", None) or getattr(shield, "install", None)
            if not callable(installer):
                raise RuntimeError("import recursion shield installer unavailable")
            installer()
            if not _shield_active():
                raise RuntimeError("process-wide compact import guard not active")
            if not _start_lifetime_monitor(shield):
                raise RuntimeError("lifetime import compactor monitor did not start")

            os.environ[_FLAG] = "1"
            _patch_release_manifest_if_loaded()
            _INSTALLED = True
            LOGGER.critical(
                "CANONICAL_IMPORT_SHIELD_V123_INSTALLED marker=%s compact_guard_active=true lifetime_monitor=true historical_wrappers_preserved=true nested_import_recursion_bounded=true safety_gates_unchanged=true",
                MARKER,
            )
            return True
        except BaseException as exc:
            os.environ.pop(_FLAG, None)
            _INSTALLED = False
            LOGGER.critical(
                "CANONICAL_IMPORT_SHIELD_V123_INSTALL_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_shield_active",
    "_patch_release_manifest_if_loaded",
    "_start_lifetime_monitor",
]
