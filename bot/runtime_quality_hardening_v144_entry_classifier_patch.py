"""Tighten v144 entry classification for long and short exposure.

Any request explicitly marked as an entry is exposure-increasing unless it is
reduce-only or carries an explicit reduce/exit/close/liquidate intent/effect.
This prevents sell/short entry requests from bypassing the v144 reconciliation
entry gate while preserving every explicit risk-reducing path.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from bot import runtime_quality_hardening_v144_patch as v144

LOGGER = logging.getLogger("nija.runtime_quality_hardening_v144_entry_classifier")
MARKER = "20260818-runtime-quality-hardening-v144-entry-classifier"
_FLAG = "NIJA_RUNTIME_QUALITY_HARDENING_V144_ENTRY_CLASSIFIER_INSTALLED"


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


def install_import_hook() -> bool:
    v144._entry_increases_exposure = _entry_increases_exposure
    # Re-run the idempotent v144 installer so any late-loaded execution module
    # is patched under the corrected classifier.
    v144.install_import_hook()
    os.environ[_FLAG] = "1"
    LOGGER.info(
        "RUNTIME_QUALITY_V144_ENTRY_CLASSIFIER_INSTALLED marker=%s long_short_entries_fail_closed=true exits_unaffected=true",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_entry_increases_exposure"]
