"""Canonical position-sync preactivation truth and release attestation v119.

Production deployment 2b43a7d2 showed the canonical readiness table with
``position_sync_ready=False`` while v61's PREACTIVATION_READINESS truth-sync
pending lists omitted that key.  The omission is diagnostic and semantic:
``NIJA_PREACTIVATION_READINESS_V16_READY`` can otherwise describe only the
legacy nine proof keys instead of the complete canonical readiness table.

v119 fixes that without making v61 a second publisher of position-sync truth:

* v61/v16 continue to own and update only their existing legacy readiness keys;
* ``position_sync_ready`` is observed from ``readiness_table`` and is never
  marked or revoked by this patch;
* preactivation remains false while that canonical key is missing or false;
* the v61 activation-prerequisite boundary independently observes the same key;
* the runtime release manifest explicitly attests v98, v116, v117, v118, and
  v119 so a release cannot report complete while those repairs are absent;
* no new ``builtins.__import__`` hook is installed.

No readiness, position, writer, nonce, capital, risk, or execution permission is
fabricated by this patch.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.preactivation_position_sync_v119")
MARKER = "20260816-preactivation-position-sync-v119"
RELEASE_ID = "20260816-runtime-convergence-v119"
_PATCH_ATTR = "_nija_preactivation_position_sync_v119"
_LOCK = threading.RLock()
_INSTALLED = False


def _module(*names: str) -> ModuleType | None:
    for name in names:
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            return mod
    for name in names:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        if isinstance(mod, ModuleType):
            return mod
    return None


def _readiness_table_module() -> ModuleType | None:
    return _module("bot.readiness_table", "readiness_table")


def _position_sync_truth() -> tuple[bool, str, dict[str, Any]]:
    table = _readiness_table_module()
    if table is None:
        return False, "readiness_table_unavailable", {}
    try:
        snapshot = dict(table.snapshot() or {})
    except Exception as exc:
        return False, f"readiness_snapshot_failed:{type(exc).__name__}:{exc}", {}
    if "position_sync_ready" not in snapshot:
        return False, "position_sync_ready_missing", snapshot
    return bool(snapshot.get("position_sync_ready", False)), "canonical_readiness_table", snapshot


def _patch_truth_sync(v61: ModuleType, v16: ModuleType) -> bool:
    current = getattr(v16, "_mark_proven_readiness", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    legacy_keys = tuple(getattr(v61, "_KEYS", ()) or ())
    if not legacy_keys:
        return False
    state_value = getattr(v61, "_state_value", None)
    if not callable(state_value):
        return False

    @wraps(current)
    def mark_proven_readiness_v119(proofs: dict[str, bool]) -> tuple[bool, list[str]]:
        table = _readiness_table_module()
        if table is None:
            os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "0"
            return False, ["readiness_table_unavailable", "position_sync_ready"]

        try:
            before = dict(table.snapshot() or {})
        except Exception as exc:
            os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "0"
            return False, [f"readiness_snapshot_failed:{type(exc).__name__}:{exc}", "position_sync_ready"]

        trading_state = str(state_value() or "UNAVAILABLE")
        prelive = trading_state != "LIVE_ACTIVE"
        for key in legacy_keys:
            if bool(proofs.get(key, False)):
                table.mark_ready(key)
            elif prelive:
                table.revoke_ready(key, reason="v119_current_proof_false")

        try:
            after = dict(table.snapshot() or {})
        except Exception as exc:
            os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "0"
            return False, [f"readiness_snapshot_failed:{type(exc).__name__}:{exc}", "position_sync_ready"]

        current_pending = [key for key in legacy_keys if not bool(proofs.get(key, False))]
        table_pending = [key for key in legacy_keys if not bool(after.get(key, False))]
        position_ready = bool(after.get("position_sync_ready", False))
        position_source = "canonical_readiness_table" if "position_sync_ready" in after else "missing"
        if not position_ready:
            table_pending.append("position_sync_ready")

        pending: list[str] = []
        for key in (*current_pending, *table_pending):
            if key not in pending:
                pending.append(key)
        ready = not pending

        os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "1" if ready else "0"
        if prelive:
            authority = bool(proofs.get("authority_ready", False))
            nonce = bool(proofs.get("nonce_ready", False))
            os.environ["NIJA_AUTHORITY_READY"] = "1" if authority else "0"
            os.environ["NIJA_NONCE_READY"] = "1" if nonce else "0"
            os.environ["NIJA_RUNTIME_NONCE_READY"] = "1" if nonce else "0"

        LOGGER.critical(
            "PREACTIVATION_READINESS_V119_TRUTH_SYNC marker=%s state=%s prelive=%s before=%s after=%s current_pending=%s table_pending=%s pending=%s position_sync_ready=%s position_source=%s canonical_position_publisher_preserved=true",
            MARKER,
            trading_state,
            str(prelive).lower(),
            before,
            after,
            current_pending,
            table_pending,
            pending,
            position_ready,
            position_source,
        )
        if ready:
            LOGGER.critical(
                "PREACTIVATION_READY marker=%s authority_ready=%s nonce_ready=%s position_sync_ready=true writer_authority=confirmed blockers_cleared=true current_proofs=true",
                MARKER,
                bool(proofs.get("authority_ready", False)),
                bool(proofs.get("nonce_ready", False)),
            )
        return ready, pending

    setattr(mark_proven_readiness_v119, _PATCH_ATTR, True)
    setattr(mark_proven_readiness_v119, "__wrapped__", current)
    v16._mark_proven_readiness = mark_proven_readiness_v119
    return True


def _patch_activation_prerequisites(v61: ModuleType) -> bool:
    current = getattr(v61, "_activation_prerequisites", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def activation_prerequisites_v119() -> tuple[bool, list[str], dict[str, Any]]:
        ready, blockers, details = current()
        position_ready, position_source, snapshot = _position_sync_truth()
        final_details = dict(details or {})
        final_details["position_sync_readiness"] = {
            "ready": position_ready,
            "source": position_source,
            "table_value": snapshot.get("position_sync_ready") if snapshot else None,
        }
        final_blockers = list(blockers or [])
        if not position_ready and "position_sync_ready" not in final_blockers:
            final_blockers.append("position_sync_ready")
        if final_blockers:
            return False, final_blockers, final_details
        return bool(ready), final_blockers, final_details

    setattr(activation_prerequisites_v119, _PATCH_ATTR, True)
    setattr(activation_prerequisites_v119, "__wrapped__", current)
    v61._activation_prerequisites = activation_prerequisites_v119
    return True


def _patch_release_manifest(manifest: ModuleType) -> bool:
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required.update(
        {
            "position_sync_timeout_v98": "NIJA_POSITION_SYNC_TIMEOUT_V98_INSTALLED",
            "runtime_convergence_v116": "NIJA_RUNTIME_CONVERGENCE_V116_INSTALLED",
            "position_fetch_generation_v117": "NIJA_POSITION_FETCH_GENERATION_V117_INSTALLED",
            "terminal_writer_loss_seak_v118": "NIJA_TERMINAL_WRITER_LOSS_SEAK_V118_INSTALLED",
            "preactivation_position_sync_v119": "NIJA_PREACTIVATION_POSITION_SYNC_V119_INSTALLED",
        }
    )
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True

        v61 = _module("bot.final_production_activation_repair_v61_patch", "final_production_activation_repair_v61_patch")
        if v61 is None:
            return False
        v61_install = getattr(v61, "install", None)
        if callable(v61_install) and v61_install() is False:
            return False

        v16 = _module("preactivation_readiness_convergence_v16_patch", "bot.preactivation_readiness_convergence_v16_patch")
        manifest = _module("bot.runtime_release_manifest_patch", "runtime_release_manifest_patch")
        if v16 is None or manifest is None:
            return False

        truth_ok = _patch_truth_sync(v61, v16)
        activation_ok = _patch_activation_prerequisites(v61)
        if not (truth_ok and activation_ok):
            return False

        os.environ["NIJA_PREACTIVATION_POSITION_SYNC_V119_INSTALLED"] = "1"
        manifest_ok = _patch_release_manifest(manifest)
        if not manifest_ok:
            os.environ.pop("NIJA_PREACTIVATION_POSITION_SYNC_V119_INSTALLED", None)
            return False

        _INSTALLED = True
        LOGGER.critical(
            "PREACTIVATION_POSITION_SYNC_V119_INSTALLED marker=%s canonical_position_publisher_preserved=true position_sync_required_for_preactivation=true release_attestation=v98,v116,v117,v118,v119 import_hook_added=false safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v119 deliberately installs no import hook."""
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_truth_sync",
    "_patch_activation_prerequisites",
    "_patch_release_manifest",
]
