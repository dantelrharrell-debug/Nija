"""Prevent local hard-stop blocks from poisoning exchange rejection telemetry (v224).

A production run on 2026-08-24 showed that ExecutionPipeline reports synthetic
pipeline failures to ExchangeKillSwitchProtector with order IDs prefixed by
``exec-reject:pipeline:``. When the canonical global kill switch is already
active, those failures are local fail-closed blocks: no exchange order is sent.
Counting them as exchange rejections creates a self-amplifying feedback loop
where the stop itself increases the rejection-rate sample.

v224 makes one narrow behavioral change: while the canonical global kill switch
is already active, synthetic pipeline rejection IDs are excluded from the
exchange-rejection rolling window. Real broker/exchange order results, synthetic
pipeline failures observed before a global hard stop, accepted orders, rejection
thresholds, minimum sample size, and all kill-switch activation/deactivation
semantics remain unchanged.

This patch never deactivates a kill switch, clears EMERGENCY_STOP, modifies
readiness, grants execution authority, fabricates order/fill proof, or forces
LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.exchange_reject_provenance_v224")
MARKER = "20260824-exchange-reject-provenance-v224"
_FLAG = "NIJA_EXCHANGE_REJECT_PROVENANCE_V224_READY"
_PATCH_ATTR = "_nija_exchange_reject_provenance_v224"
_SYNTHETIC_PREFIX = "exec-reject:pipeline:"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None


def _is_synthetic_pipeline_reject(order_id: Any) -> bool:
    return str(order_id or "").strip().lower().startswith(_SYNTHETIC_PREFIX)


def _global_stop_active(protector: Any) -> bool:
    probe = getattr(protector, "_global_kill_switch_active", None)
    if not callable(probe):
        return False
    try:
        return probe() is True
    except Exception:
        return False


def _patch_record_order_result() -> bool:
    module = importlib.import_module("bot.exchange_kill_switch")
    cls = getattr(module, "ExchangeKillSwitchProtector", None)
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "record_order_result", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def record_order_result_v224(
        self: Any,
        order_id: str,
        accepted: bool,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        # A synthetic pipeline failure while the canonical global stop is
        # already active is a local fail-closed outcome, not an exchange order
        # rejection. No broker request was permitted to leave the pipeline.
        if (
            accepted is False
            and _is_synthetic_pipeline_reject(order_id)
            and _global_stop_active(self)
        ):
            LOGGER.critical(
                "EXCHANGE_REJECT_V224_LOCAL_STOP_IGNORED marker=%s order_id=%s "
                "global_kill_switch_active=true synthetic_pipeline_reject=true "
                "exchange_sample_mutated=false real_exchange_results_unchanged=true "
                "kill_switch_unchanged=true execution_authority_unchanged=true",
                MARKER,
                str(order_id)[:256],
            )
            return None
        return current(self, order_id, accepted, *args, **kwargs)

    setattr(record_order_result_v224, _PATCH_ATTR, True)
    setattr(record_order_result_v224, "__wrapped__", current)
    setattr(cls, "record_order_result", record_order_result_v224)
    return True


def _register_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict) or not isinstance(installers, tuple):
        return False
    required["exchange_reject_provenance_v224"] = _FLAG
    own = ("bot.exchange_reject_provenance_v224_patch", "install_import_hook")
    if own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _worker() -> None:
    while True:
        try:
            _patch_record_order_result()
            _register_manifest()
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECT_PROVENANCE_V224_REASSERT_ERROR marker=%s err=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(5.0)


def install() -> bool:
    global _THREAD
    if not _patch_record_order_result():
        return False
    os.environ[_FLAG] = "1"
    _register_manifest()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ExchangeRejectProvenanceV224",
                daemon=True,
            )
            _THREAD.start()
    LOGGER.critical(
        "EXCHANGE_REJECT_PROVENANCE_V224_READY marker=%s ready=true "
        "synthetic_pipeline_blocks_while_global_stop_ignored=true "
        "real_exchange_results_unchanged=true pre_stop_synthetic_results_unchanged=true "
        "thresholds_unchanged=true minimum_sample_unchanged=true auto_recovery=false "
        "kill_switch_unchanged=true execution_authority_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_is_synthetic_pipeline_reject",
    "_global_stop_active",
    "_patch_record_order_result",
]
