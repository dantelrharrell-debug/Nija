"""Heartbeat verification truth convergence v351.

Fresh Render evidence on 2026-09-03 exposed two terminal liveness/provenance
regressions after v349/v350 were already loaded:

* a HEARTBEAT_TRADE can return
  ``confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s`` with no
  order id and no confirmed exchange rejection.  Lower exchange-health telemetry
  already classifies that condition as a soft reject and does not mutate the
  exchange sample, but the strategy-level rejected-order anomaly still counted
  it toward the execution circuit breaker.  v351 classifies only that exact
  no-confirmed-fill timeout family as a non-exchange rejection.  An explicit
  rejected status or any order id remains exchange provenance and still counts.
* the canonical pre-trade validator can observe a late-mutated
  ``bot.trading_state_machine`` without ``_required_heartbeat_stage``.  v351
  reasserts the existing live-execution heartbeat helper contract immediately
  before ``can_execute``; the original validator decision remains authoritative.

This patch never clears a circuit breaker, never promotes an ACK to a fill,
never grants readiness, never fabricates heartbeat/execution proof, and never
bypasses writer, nonce, risk, capital, kill-switch, position-sync, ECEL,
minimum-order, broker-health, order-ack or confirmed-fill gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_verification_truth_v351")
MARKER = "20260903-runtime-heartbeat-verification-truth-v351"
RELEASE_ID = "20260903-runtime-convergence-v351"
_READY_FLAG = "NIJA_RUNTIME_HEARTBEAT_VERIFICATION_TRUTH_V351_READY"
_LOCK = threading.RLock()
_CAN_EXECUTE_PATCH = "_nija_v351_heartbeat_helper_terminal_reassert"
_ACK_TIMEOUT_MARKER = "ack_timeout_no_confirmed_fill_within_"


def _repair_heartbeat_stage_helpers() -> bool:
    try:
        repair = importlib.import_module("bot.live_execution_authority_blocker_patch")
        patcher = getattr(repair, "_patch_trading_state_machine", None)
        if not callable(patcher):
            return False
        canonical = importlib.import_module("bot.trading_state_machine")
        patcher(canonical)
        try:
            alias = importlib.import_module("trading_state_machine")
            patcher(alias)
        except Exception:
            pass
        required = (
            "_required_heartbeat_stage",
            "heartbeat_marker_is_fresh",
            "heartbeat_marker_stage_is_sufficient",
        )
        return all(callable(getattr(canonical, name, None)) for name in required)
    except Exception:
        LOGGER.exception("HEARTBEAT_HELPER_V351_REASSERT_FAILED marker=%s fail_closed=true", MARKER)
        return False


def _patch_terminal_can_execute_reassertion() -> bool:
    try:
        eac = importlib.import_module("bot.execution_authority_context")
        current = getattr(eac, "can_execute", None)
        if not callable(current):
            return False
        if bool(getattr(current, _CAN_EXECUTE_PATCH, False)):
            return True
        original = current

        @wraps(original)
        def can_execute_v351(*args: Any, **kwargs: Any):
            # Reassert compatibility helpers only.  If repair fails, the original
            # validator still runs and remains fail-closed; no decision is changed.
            _repair_heartbeat_stage_helpers()
            return original(*args, **kwargs)

        setattr(can_execute_v351, _CAN_EXECUTE_PATCH, True)
        setattr(can_execute_v351, "__wrapped__", original)
        eac.can_execute = can_execute_v351
        return True
    except Exception:
        LOGGER.exception("HEARTBEAT_CAN_EXECUTE_V351_PATCH_FAILED marker=%s fail_closed=true", MARKER)
        return False


def _patch_ack_timeout_rejection_truth() -> bool:
    try:
        v349 = importlib.import_module("bot.runtime_terminal_exit_heartbeat_truth_v349_patch")
        markers = getattr(v349, "_LOCAL_HEARTBEAT_ERROR_MARKERS", None)
        if not isinstance(markers, tuple):
            return False
        if _ACK_TIMEOUT_MARKER not in markers:
            v349._LOCAL_HEARTBEAT_ERROR_MARKERS = markers + (_ACK_TIMEOUT_MARKER,)
        return _ACK_TIMEOUT_MARKER in getattr(v349, "_LOCAL_HEARTBEAT_ERROR_MARKERS", ())
    except Exception:
        LOGGER.exception("HEARTBEAT_ACK_TIMEOUT_V351_PATCH_FAILED marker=%s fail_closed=true", MARKER)
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_heartbeat_verification_truth_v351"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        helpers = terminal = timeout_truth = manifest = False
        try:
            helpers = _repair_heartbeat_stage_helpers()
            terminal = _patch_terminal_can_execute_reassertion()
            timeout_truth = _patch_ack_timeout_rejection_truth()
            manifest = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_HEARTBEAT_VERIFICATION_TRUTH_V351_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        ready = bool(helpers and terminal and timeout_truth and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_HEARTBEAT_VERIFICATION_TRUTH_V351_%s marker=%s ready=%s "
            "heartbeat_helpers_reasserted=%s terminal_can_execute_reassertion=%s "
            "ack_timeout_rejection_truth=%s manifest=%s "
            "ack_timeout_without_order_id_not_exchange_rejection=true "
            "explicit_rejected_status_counts=true order_id_provenance_counts=true "
            "ack_not_fill=true confirmed_fill_required=true circuit_breaker_not_cleared=true "
            "readiness_not_granted=true execution_proof_fabricated=false forced_trade=false forced_activation=false "
            "writer_nonce_risk_capital_killswitch_position_sync_ecel_minimum_order_broker_health_order_ack_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
            str(helpers).lower(),
            str(terminal).lower(),
            str(timeout_truth).lower(),
            str(manifest).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_repair_heartbeat_stage_helpers",
    "_patch_ack_timeout_rejection_truth",
]
