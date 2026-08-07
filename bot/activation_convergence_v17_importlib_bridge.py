"""Importlib bridge for activation convergence v17.

NIJA loads several runtime repair modules with importlib.import_module(), which
can bypass wrappers installed only around builtins.__import__.  This bridge keeps
the v17 convergence patch applied to both ordinary imports and importlib-loaded
modules without importing runtime modules early.
"""
from __future__ import annotations

import builtins
import importlib
import logging
from typing import Any

from bot import activation_convergence_v17_patch as convergence

logger = logging.getLogger("nija.activation_convergence_v17_importlib_bridge")
_FLAG = "_NIJA_ACTIVATION_CONVERGENCE_V17_IMPORTLIB_BRIDGE"
_TARGETS = (
    "entrypoint_writer_authority",
    "authority_heartbeat",
    "startup_coordinator",
    "writer_authority_recursion_guard_patch",
    "preactivation_readiness_convergence_v16_patch",
    "secondary_venue_activation_patch",
    "activation_pending_commit_monitor_patch",
)


def install_import_hook() -> None:
    convergence._patch_loaded()
    if getattr(builtins, _FLAG, False):
        return

    original = importlib.import_module

    def importing(name: str, package: str | None = None) -> Any:
        module = original(name, package)
        if any(str(name).endswith(target) for target in _TARGETS):
            try:
                convergence._patch_loaded()
            except Exception:
                logger.exception(
                    "ACTIVATION_CONVERGENCE_V17_IMPORTLIB_PATCH_FAILED imported=%s",
                    name,
                )
        return module

    importlib.import_module = importing  # type: ignore[assignment]
    setattr(builtins, _FLAG, True)
    logger.warning("ACTIVATION_CONVERGENCE_V17_IMPORTLIB_BRIDGE_INSTALLED")


def install() -> None:
    install_import_hook()
