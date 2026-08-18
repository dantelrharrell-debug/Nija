"""Tighten v144 entry classification and release-contract enforcement.

Any request explicitly marked as an entry is exposure-increasing unless it is
reduce-only or carries an explicit reduce/exit/close/liquidate intent/effect.
This prevents sell/short entry requests from bypassing the v144 reconciliation
entry gate while preserving every explicit risk-reducing path.

The module also registers v144 as a required runtime-release proof as soon as
the release manifest is available. That keeps the control-plane readiness
contract aligned with the entry-safety layer instead of allowing an older
manifest to report ready while v144 is unavailable.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

from bot import runtime_quality_hardening_v144_patch as v144

LOGGER = logging.getLogger("nija.runtime_quality_hardening_v144_entry_classifier")
MARKER = "20260818-runtime-quality-hardening-v144-entry-classifier"
_FLAG = "NIJA_RUNTIME_QUALITY_HARDENING_V144_ENTRY_CLASSIFIER_INSTALLED"
_CONTRACT_FLAG = "NIJA_RUNTIME_QUALITY_HARDENING_V144_RELEASE_CONTRACT_READY"
_MONITOR_STARTED = False
_LOCK = threading.RLock()


def _entry_increases_exposure(request: Any) -> bool:
    if bool(getattr(request, "reduce_only", False)):
        return False
    intent = str(getattr(request, "intent_type", "entry") or "entry").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    reducing = {"reduce", "exit", "close", "liquidate", "liquidation"}
    if intent in reducing or effect in reducing:
        return False
    # For safety, all remaining entry/unknown intents are treated as increasing
    # exposure regardless of whether the side is buy/long or sell/short.
    return True


def _patch_manifest_contract() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["runtime_quality_hardening_v144"] = "NIJA_RUNTIME_QUALITY_HARDENING_V144_READY"
    required["runtime_quality_v144_entry_classifier"] = _FLAG
    required["runtime_quality_v144_release_contract"] = _CONTRACT_FLAG
    # v144 is the terminal release owner. Update DECLARED_RELEASE_ID before the
    # compatibility name because v139 guards assignments to RELEASE_ID.
    manifest.DECLARED_RELEASE_ID = v144.RELEASE_ID
    manifest.RELEASE_ID = v144.RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = v144.RELEASE_ID
    os.environ[_CONTRACT_FLAG] = "1"
    return True


def _manifest_monitor() -> None:
    deadline = time.monotonic() + max(
        60.0,
        float(os.environ.get("NIJA_RUNTIME_QUALITY_V144_MONITOR_S", "600") or 600.0),
    )
    while time.monotonic() < deadline:
        try:
            if _patch_manifest_contract():
                LOGGER.info(
                    "RUNTIME_QUALITY_V144_RELEASE_CONTRACT_READY marker=%s release=%s",
                    MARKER,
                    v144.RELEASE_ID,
                )
                return
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_QUALITY_V144_RELEASE_CONTRACT_ERROR marker=%s error=%s",
                MARKER,
                exc,
            )
        time.sleep(0.25)
    os.environ[_CONTRACT_FLAG] = "0"
    LOGGER.critical(
        "RUNTIME_QUALITY_V144_RELEASE_CONTRACT_TIMEOUT marker=%s release=%s trading_fail_closed=true",
        MARKER,
        v144.RELEASE_ID,
    )


def install_import_hook() -> bool:
    global _MONITOR_STARTED
    v144._entry_increases_exposure = _entry_increases_exposure
    # Re-run the idempotent v144 installer so any late-loaded execution module
    # is patched under the corrected classifier.
    v144.install_import_hook()
    os.environ[_FLAG] = "1"
    if _patch_manifest_contract():
        os.environ[_CONTRACT_FLAG] = "1"
    else:
        with _LOCK:
            if not _MONITOR_STARTED:
                _MONITOR_STARTED = True
                threading.Thread(
                    target=_manifest_monitor,
                    name="RuntimeQualityV144ReleaseContract",
                    daemon=True,
                ).start()
    LOGGER.info(
        "RUNTIME_QUALITY_V144_ENTRY_CLASSIFIER_INSTALLED marker=%s long_short_entries_fail_closed=true exits_unaffected=true release_contract_monitored=true",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_entry_increases_exposure",
    "_patch_manifest_contract",
]
