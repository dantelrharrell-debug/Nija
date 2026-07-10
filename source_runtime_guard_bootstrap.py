"""Earliest source-level runtime guard bootstrap for NIJA.

This module is intentionally located at repository root and imports no ``bot``
package modules.  ``main.py`` calls :func:`install` before its first ``bot.*``
import so venue-readiness enforcement does not depend on Docker ``.pth`` files
or provider-specific startup behavior.

The bootstrap does not grant writer authority, mark a broker connected, create
credentials, or relax risk controls.  In a live-capital process it fails closed
when the mandatory venue repair cannot be installed.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("nija.source_runtime_guard_bootstrap")

_MARKER = "20260710af"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUTHY


def _is_live_runtime() -> bool:
    """Return whether startup is expected to control real exchange capital."""

    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False
    return any(
        _truthy(name)
        for name in (
            "LIVE_CAPITAL_VERIFIED",
            "NIJA_EXECUTION_ACTIVE",
            "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        )
    )


def _deployment_commit() -> str:
    for name in (
        "RENDER_GIT_COMMIT",
        "GIT_COMMIT",
        "RAILWAY_GIT_COMMIT_SHA",
        "COMMIT_SHA",
        "SOURCE_VERSION",
    ):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return "unknown"


def install() -> bool:
    """Install mandatory source-level venue guards exactly once.

    The underlying repair is idempotent and continuously patches late imports.
    A live process must terminate through the caller when installation fails;
    returning ``False`` is reserved for non-live development/test processes.
    """

    global _INSTALLED

    with _LOCK:
        if _INSTALLED:
            return True

        try:
            repair = importlib.import_module("venue_readiness_execution_repair_patch")
            installer = getattr(repair, "install", None) or getattr(
                repair, "install_import_hook", None
            )
            if not callable(installer):
                raise RuntimeError("venue readiness repair installer is missing")

            installer()
            _INSTALLED = True
            os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] = "1"
            os.environ["NIJA_VENUE_READINESS_SOURCE_MARKER"] = _MARKER

            commit = _deployment_commit()
            logger.warning(
                "SOURCE_RUNTIME_GUARDS_READY marker=%s commit=%s "
                "venue_repair=installed source=main_pre_bot",
                _MARKER,
                commit,
            )
            print(
                f"[NIJA-PRINT] SOURCE_RUNTIME_GUARDS_READY marker={_MARKER} "
                f"commit={commit} venue_repair=installed source=main_pre_bot",
                flush=True,
            )
            return True
        except Exception as exc:
            os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] = "0"
            os.environ["NIJA_VENUE_READINESS_SOURCE_MARKER"] = _MARKER
            message = f"{type(exc).__name__}:{exc}"
            logger.critical(
                "SOURCE_RUNTIME_GUARDS_FAILED marker=%s commit=%s error=%s "
                "live=%s",
                _MARKER,
                _deployment_commit(),
                message,
                _is_live_runtime(),
                exc_info=True,
            )
            print(
                f"[NIJA-PRINT] SOURCE_RUNTIME_GUARDS_FAILED marker={_MARKER} "
                f"commit={_deployment_commit()} error={message[:240]} "
                f"live={str(_is_live_runtime()).lower()}",
                flush=True,
            )
            if _is_live_runtime():
                raise RuntimeError(
                    "live startup blocked: mandatory venue readiness repair failed"
                ) from exc
            return False


def installed_marker() -> Optional[str]:
    return _MARKER if _INSTALLED else None


__all__ = ["install", "installed_marker"]
