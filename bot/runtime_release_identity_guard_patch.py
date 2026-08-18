"""Keep runtime release identity owned by the canonical manifest.

Older convergence modules may register their required flags with the runtime
manifest, but they must never rewrite the manifest's active release identity.
Production v138 exposed that v136 still assigned ``manifest.RELEASE_ID`` during
every audit, causing a v138 deployment to report itself as v136.

This guard is deliberately observational/control-plane only. It does not alter
trading state, readiness, capital freshness, kill-switch state, writer/nonce
authority, risk, sizing, or execution gates.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_release_identity_guard")
MARKER = "20260817-runtime-release-identity-guard-v1"
_FLAG = "NIJA_RUNTIME_RELEASE_IDENTITY_GUARD_INSTALLED"
_LOCK = threading.RLock()
_INSTALLED = False


def _declared_release(manifest: Any) -> str:
    value = str(getattr(manifest, "DECLARED_RELEASE_ID", "") or "").strip()
    if value:
        return value
    return str(getattr(manifest, "RELEASE_ID", "") or "").strip()


def _patch_v136_manifest_registration() -> bool:
    """Make v136 register only its flag, never own the parent release ID."""
    from bot import activation_publication_convergence_v136_patch as v136
    from bot import runtime_release_manifest_patch as manifest

    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False

    def register_v136_without_release_override() -> bool:
        current_required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(current_required, dict):
            return False
        current_required["activation_publication_convergence_v136"] = (
            "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED"
        )
        return True

    register_v136_without_release_override._nija_release_identity_guard = True  # type: ignore[attr-defined]
    v136._patch_release_manifest = register_v136_without_release_override
    return True


def _restore_manifest_identity() -> bool:
    from bot import runtime_release_manifest_patch as manifest

    declared = _declared_release(manifest)
    if not declared:
        return False
    previous = str(getattr(manifest, "RELEASE_ID", "") or "").strip()
    manifest.RELEASE_ID = declared
    if previous and previous != declared:
        LOGGER.critical(
            "RUNTIME_RELEASE_IDENTITY_DRIFT_REPAIRED marker=%s previous=%s declared=%s",
            MARKER,
            previous,
            declared,
        )
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            ok = _patch_v136_manifest_registration() and _restore_manifest_identity()
        except Exception as exc:
            LOGGER.critical(
                "RUNTIME_RELEASE_IDENTITY_GUARD_INSTALL_FAILED marker=%s err=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            ok = False
        if not ok:
            os.environ.pop(_FLAG, None)
            return False
        os.environ[_FLAG] = "1"
        _INSTALLED = True
    LOGGER.critical(
        "RUNTIME_RELEASE_IDENTITY_GUARD_INSTALLED marker=%s canonical_manifest_owner=true "
        "legacy_release_override=false readiness_unchanged=true kill_switch_unchanged=true "
        "nonce_unchanged=true risk_gates_unchanged=true execution_authority_unchanged=true",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_declared_release",
    "_patch_v136_manifest_registration",
    "_restore_manifest_identity",
]
