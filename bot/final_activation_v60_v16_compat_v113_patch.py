"""Compatibility bridge for v60 against current preactivation v16 API.

Production v112 proved the canonical fast-path import and build fixes, then
failed because final_production_activation_repair_v60_patch still expected
preactivation_readiness_convergence_v16_patch._cycle. Current v16 exposes
_attempt_activation instead. This shim patches v60's private installer step
before v60.install() runs. It preserves proof collection, readiness publication,
and fail-closed activation semantics while dispatching the actual activation
commit through v60's existing single-flight worker.
"""
from __future__ import annotations

import importlib
import logging
import os
from typing import Any

LOGGER = logging.getLogger("nija.final_activation_v60_v16_compat_v113")
MARKER = "20260816-final-activation-v60-v16-compat-v113"
_INSTALLED = False


def _patch_v60() -> bool:
    v60 = importlib.import_module("bot.final_production_activation_repair_v60_patch")
    current = getattr(v60, "_patch_v16_nonblocking", None)
    if getattr(current, "_nija_v113_current_v16_api", False):
        return True

    def patch_v16_nonblocking() -> bool:
        v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
        original_attempt = getattr(v16, "_attempt_activation", None)
        if not callable(original_attempt):
            LOGGER.critical(
                "FINAL_ACTIVATION_V113_V16_API_MISSING marker=%s expected=_attempt_activation",
                MARKER,
            )
            return False
        if getattr(original_attempt, "_nija_v60_nonblocking", False):
            return True

        def attempt_activation() -> tuple[bool, dict[str, Any]]:
            proofs, details = v16._collect_proofs()
            ready, pending = v16._mark_proven_readiness(proofs)
            v60._publish_risk_compat(proofs)
            details["proofs"] = proofs
            details["pending"] = pending
            publisher_started, publisher_detail = v16._ensure_strategy_publication_monitor()
            details["strategy_publication_monitor"] = {
                "started": publisher_started,
                "detail": publisher_detail,
            }
            try:
                monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
                sm = monitor._state_machine()
                state = v60._state_value(sm) if sm is not None else "UNAVAILABLE"
            except Exception:
                state = "UNAVAILABLE"
            if ready and state != "LIVE_ACTIVE":
                dispatched = bool(v60.request_activation("v16_readiness_complete"))
            else:
                dispatched = False
            details["state_before"] = state
            details["activation_dispatched"] = dispatched
            details["activation_mode"] = "single_flight_nonblocking_v113"
            return state == "LIVE_ACTIVE", details

        attempt_activation._nija_v60_nonblocking = True  # type: ignore[attr-defined]
        attempt_activation._nija_v113_current_v16_api = True  # type: ignore[attr-defined]
        attempt_activation.__wrapped__ = original_attempt  # type: ignore[attr-defined]
        v16._attempt_activation = attempt_activation
        LOGGER.critical(
            "FINAL_ACTIVATION_V113_V16_PATCHED marker=%s api=_attempt_activation "
            "proof_publication_nonblocking=true activation_single_flight=true force_activation=false",
            MARKER,
        )
        return True

    patch_v16_nonblocking._nija_v113_current_v16_api = True  # type: ignore[attr-defined]
    patch_v16_nonblocking.__wrapped__ = current  # type: ignore[attr-defined]
    v60._patch_v16_nonblocking = patch_v16_nonblocking
    return True


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    if not _patch_v60():
        os.environ["NIJA_FINAL_ACTIVATION_V60_V16_COMPAT_V113_INSTALLED"] = "0"
        return False
    _INSTALLED = True
    os.environ["NIJA_FINAL_ACTIVATION_V60_V16_COMPAT_V113_INSTALLED"] = "1"
    LOGGER.critical(
        "FINAL_ACTIVATION_V60_V16_COMPAT_V113_INSTALLED marker=%s fail_closed=true",
        MARKER,
    )
    return True


install_import_hook = install
