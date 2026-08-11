"""Retired hard-controls compatibility patch.

HardControls rejections are authoritative.  The former implementation
monkeypatched ``HardControls.can_trade`` and could turn a capital-validation
failure into an approval based on a second, divergent readiness calculation.
Capital, writer, and execution gates are now repaired at their canonical
sources, so this installer intentionally performs no runtime mutation.
"""

from __future__ import annotations

import logging


logger = logging.getLogger("nija.hard_controls_csm_repair")
_MARKER = "20260811-hard-controls-canonical-v94"


def install_import_hook() -> bool:
    """Attest that the unsafe compatibility override is disabled."""

    logger.warning(
        "HARD_CONTROLS_CSM_REPAIR_RETIRED marker=%s "
        "runtime_monkeypatch=false hard_control_rejections_authoritative=true",
        _MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = ["install", "install_import_hook"]
