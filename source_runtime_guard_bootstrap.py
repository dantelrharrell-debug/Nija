"""Earliest source-level runtime guard bootstrap for NIJA.

This module is intentionally located at repository root and imports no ``bot``
package modules. ``main.py`` loads ``bot/global_runtime_startup_guards.py`` by
file path before its first ``bot.*`` import; that first installer calls
:func:`install`.

On Render, the Docker ``.pth`` hook deliberately leaves the replacement process
fail-closed so the shell can expose ``/healthz`` during a zero-downtime deploy.
This source bootstrap then acquires the canonical Redis writer lease before any
``bot.*`` import and installs venue-readiness, secondary-venue activation, strict
multi-venue entry admission, and the cross-process readiness bridge.

The bootstrap never deletes another instance's active lease, creates credentials,
fabricates balances, marks a broker connected, or relaxes risk controls. In a
live-capital process it fails closed when mandatory runtime guards cannot be
installed.
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


def _install_required(module_name: str) -> None:
    module = importlib.import_module(module_name)
    installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
    if not callable(installer):
        raise RuntimeError(f"{module_name} installer is missing")
    installer()


def install() -> bool:
    """Acquire writer lineage and install mandatory source guards exactly once.

    The underlying repairs are idempotent. A live process exits through
    ``SystemExit`` when installation fails. The canonical prebot writer installer
    uses a direct process exit if Redis authority cannot be established, ensuring
    Python's optional startup wrappers cannot swallow the failure.
    """

    global _INSTALLED

    with _LOCK:
        if _INSTALLED:
            return True

        try:
            # Ordering invariant: canonical Redis fencing lineage must exist before
            # any bot package import can create or inspect Kraken nonce state.
            _install_required("prebot_writer_authority_fail_closed")
            _install_required("venue_readiness_execution_repair_patch")
            _install_required("secondary_venue_activation_patch")
            _install_required("secondary_venue_strict_readiness_patch")
            _install_required("render_readiness_state_bridge")

            _INSTALLED = True
            os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] = "1"
            os.environ["NIJA_VENUE_READINESS_SOURCE_MARKER"] = _MARKER
            os.environ["NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED"] = "1"
            os.environ["NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED"] = "1"
            os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] = "1"
            os.environ["NIJA_RENDER_READINESS_BRIDGE_INSTALLED"] = "1"

            commit = _deployment_commit()
            logger.warning(
                "SOURCE_RUNTIME_GUARDS_READY marker=%s commit=%s "
                "writer_authority=installed venue_repair=installed "
                "secondary_venue_activation=installed "
                "secondary_venue_strict_readiness=installed "
                "render_readiness_bridge=installed source=main_pre_bot",
                _MARKER,
                commit,
            )
            print(
                f"[NIJA-PRINT] SOURCE_RUNTIME_GUARDS_READY marker={_MARKER} "
                f"commit={commit} writer_authority=installed venue_repair=installed "
                "secondary_venue_activation=installed "
                "secondary_venue_strict_readiness=installed "
                "render_readiness_bridge=installed source=main_pre_bot",
                flush=True,
            )
            return True
        except Exception as exc:
            os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] = "0"
            os.environ["NIJA_VENUE_READINESS_SOURCE_MARKER"] = _MARKER
            os.environ["NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED"] = "0"
            os.environ["NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED"] = "0"
            os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] = "0"
            os.environ["NIJA_RENDER_READINESS_BRIDGE_INSTALLED"] = "0"
            message = f"{type(exc).__name__}:{exc}"
            is_live = _is_live_runtime()
            logger.critical(
                "SOURCE_RUNTIME_GUARDS_FAILED marker=%s commit=%s error=%s live=%s",
                _MARKER,
                _deployment_commit(),
                message,
                is_live,
                exc_info=True,
            )
            print(
                f"[NIJA-PRINT] SOURCE_RUNTIME_GUARDS_FAILED marker={_MARKER} "
                f"commit={_deployment_commit()} error={message[:240]} "
                f"live={str(is_live).lower()}",
                flush=True,
            )
            if is_live:
                raise SystemExit(78) from exc
            return False


def installed_marker() -> Optional[str]:
    return _MARKER if _INSTALLED else None


__all__ = ["install", "installed_marker"]
