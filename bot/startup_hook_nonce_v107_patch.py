"""v107 startup convergence hardening.

Addresses two production failures observed after v106:
1. Kraken platform nonce recovery can race with another thread recreating the
   singleton after destroy_instance(), causing a second constructor to raise
   "already initialized in this process".
2. Startup import hooks can recursively re-enter their own patch path.

This patch is fail-closed: it does not mark readiness or bypass writer, nonce,
risk, bootstrap, position-sync, strategy, execution, or kill-switch gates.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.startup_hook_nonce_v107")
MARKER = "20260816-startup-hook-nonce-v107"
_LOCK = threading.RLock()
_INSTALLED = False


def _patch_kraken_nonce_rebuild() -> bool:
    try:
        from bot import global_kraken_nonce as nonce
    except ImportError:
        import global_kraken_nonce as nonce  # type: ignore[import]

    current = getattr(nonce, "rebuild_nonce_manager", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v107_serialized", False):
        return True

    rebuild_lock = threading.RLock()

    @wraps(current)
    def serialized_rebuild(*args: Any, **kwargs: Any):
        with rebuild_lock:
            # Another recovery thread may have already rebuilt the singleton
            # while this caller was waiting. Reuse it rather than destroying
            # and constructing a second platform manager.
            cls = getattr(nonce, "KrakenNonceManager", None)
            existing = getattr(cls, "_instance", None) if cls is not None else None
            alias = getattr(nonce, "_nonce_manager", None)
            if existing is not None:
                if alias is not existing:
                    setattr(nonce, "_nonce_manager", existing)
                LOGGER.warning(
                    "KRAKEN_NONCE_V107_REBUILD_COALESCED marker=%s reason=live_singleton_present reuse=true",
                    MARKER,
                )
                return existing
            return current(*args, **kwargs)

    setattr(serialized_rebuild, "_nija_v107_serialized", True)
    setattr(serialized_rebuild, "_nija_v107_original", current)
    setattr(nonce, "rebuild_nonce_manager", serialized_rebuild)
    LOGGER.critical(
        "KRAKEN_NONCE_V107_REBUILD_PATCHED marker=%s serialized=true reuse_existing_singleton=true nonce_gate_unchanged=true",
        MARKER,
    )
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        if not _patch_kraken_nonce_rebuild():
            LOGGER.critical(
                "STARTUP_HOOK_NONCE_V107_INSTALL_FAILED marker=%s component=kraken_nonce trading_fail_closed=true",
                MARKER,
            )
            return False
        os.environ["NIJA_STARTUP_HOOK_NONCE_V107_INSTALLED"] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "STARTUP_HOOK_NONCE_V107_INSTALLED marker=%s nonce_rebuild_race_safe=true import_reentry_guard=v99 safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
