"""Compatibility shim for the retired activation-convergence monkeypatch.

Activation, capital-state compatibility, and writer-renewal checks now live in
their owning modules. Importing this legacy module is intentionally side-effect
free so it cannot wrap global import machinery or mutate process-wide classes.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("nija.activation_convergence_v17")

_MARKER = "20260807-activation-convergence-v17"


def install_import_hook() -> bool:
    """Keep legacy startup callers compatible without installing a hook."""

    logger.info(
        "ACTIVATION_CONVERGENCE_V17_RETIRED marker=%s "
        "runtime_monkeypatch=false direct_source_controls=true",
        _MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = ["install", "install_import_hook"]
