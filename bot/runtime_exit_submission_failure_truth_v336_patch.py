"""Exit submission failure truth v336.

v67 correctly separates submission from fill confirmation, but its immediate path
also checks whether the broker position disappeared. Production exposed a false
positive shape: v334 returned ``status=error`` with no order id because the
capability matrix rejected the order, then an empty/unproven native position
read made v67 log ``CONFIRMED_IMMEDIATE``.

A rejected or unacknowledged submission cannot have caused a position reduction.
v336 therefore suppresses *only the immediate position-disappearance proof* for
the same symbol after a terminal failure or a response that lacks submission
acknowledgement. Pending-order reconciliation and independently observed broker
position reductions remain unchanged.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_exit_submission_failure_truth_v336")
MARKER = "20260901-runtime-exit-submission-failure-truth-v336"
RELEASE_ID = "20260901-runtime-convergence-v336"
_READY_FLAG = "NIJA_RUNTIME_EXIT_SUBMISSION_FAILURE_TRUTH_V336_READY"
_SUBMIT_ATTR = "_nija_exit_failure_truth_submit_v336"
_CONFIRM_ATTR = "_nija_exit_failure_truth_confirm_v336"
_INSTALL_FLAG = "_NIJA_RUNTIME_EXIT_SUBMISSION_FAILURE_TRUTH_V336"
_LOCK = threading.RLock()
_LOCAL = threading.local()


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _symbol_from_pos(universal: Any, pos: Mapping[str, Any]) -> str:
    try:
        return str(universal.auto_exit._sym(pos.get("symbol")) or "").upper()
    except Exception:
        return str(pos.get("symbol") or "").upper()


def _patch_v67() -> bool:
    v67 = importlib.import_module("bot.universal_exit_fill_reconciliation_v67_patch")
    submit = getattr(v67, "_submit_exit_once", None)
    confirm = getattr(v67, "_confirm_by_position", None)
    if not callable(submit) or not callable(confirm):
        return False

    if not bool(getattr(submit, _SUBMIT_ATTR, False)):
        original_submit = submit

        @wraps(original_submit)
        def submit_with_failure_truth(universal: Any, broker: Any, pos: dict[str, Any], market: float):
            result = original_submit(universal, broker, pos, market)
            payload = result if isinstance(result, Mapping) else {}
            terminal_failure = bool(getattr(v67, "_is_terminal_failure")(payload))
            acknowledged = bool(getattr(v67, "_is_submission_ack")(payload))
            if terminal_failure or not acknowledged:
                _LOCAL.block = {
                    "symbol": _symbol_from_pos(universal, pos),
                    "at": time.monotonic(),
                    "status": _norm(getattr(v67, "_status")(payload)),
                    "order_id": str(getattr(v67, "_order_id")(payload) or ""),
                }
                LOGGER.warning(
                    "EXIT_FAILURE_TRUTH_V336_IMMEDIATE_POSITION_CONFIRM_BLOCK_ARMED marker=%s "
                    "venue=%s symbol=%s status=%s order_id=%s terminal_failure=%s acknowledged=%s "
                    "tracker_preserved=true fill_fabricated=false safety_gates_bypassed=false",
                    MARKER,
                    getattr(universal.auto_exit, "_broker_label")(broker),
                    _LOCAL.block["symbol"],
                    _LOCAL.block["status"] or "none",
                    _LOCAL.block["order_id"] or "none",
                    str(terminal_failure).lower(),
                    str(acknowledged).lower(),
                )
            else:
                _LOCAL.block = None
            return result

        setattr(submit_with_failure_truth, _SUBMIT_ATTR, True)
        setattr(submit_with_failure_truth, "__wrapped__", original_submit)
        v67._submit_exit_once = submit_with_failure_truth

    confirm = getattr(v67, "_confirm_by_position", None)
    if callable(confirm) and not bool(getattr(confirm, _CONFIRM_ATTR, False)):
        original_confirm = confirm

        @wraps(original_confirm)
        def confirm_with_failure_truth(universal: Any, broker: Any, pending: Mapping[str, Any]) -> bool:
            block = getattr(_LOCAL, "block", None)
            target = str(pending.get("symbol") or "").upper()
            if isinstance(block, Mapping):
                age = max(0.0, time.monotonic() - float(block.get("at") or 0.0))
                if age <= 2.0 and target and target == str(block.get("symbol") or "").upper():
                    _LOCAL.block = None
                    LOGGER.critical(
                        "EXIT_FAILURE_TRUTH_V336_FALSE_POSITION_CONFIRM_PREVENTED marker=%s symbol=%s "
                        "submission_status=%s order_id=%s immediate_position_disappearance_ignored=true "
                        "independent_future_reconciliation_preserved=true fill_fabricated=false "
                        "safety_gates_bypassed=false",
                        MARKER,
                        target,
                        block.get("status") or "none",
                        block.get("order_id") or "none",
                    )
                    return False
                if age > 2.0:
                    _LOCAL.block = None
            return bool(original_confirm(universal, broker, pending))

        setattr(confirm_with_failure_truth, _CONFIRM_ATTR, True)
        setattr(confirm_with_failure_truth, "__wrapped__", original_confirm)
        v67._confirm_by_position = confirm_with_failure_truth

    return bool(
        getattr(getattr(v67, "_submit_exit_once", None), _SUBMIT_ATTR, False)
        and getattr(getattr(v67, "_confirm_by_position", None), _CONFIRM_ATTR, False)
    )


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_exit_submission_failure_truth_v336"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_EXIT_CAPABILITY_SEMANTICS_V335_READY") != "1":
                raise RuntimeError("v335_not_ready")
            patched = _patch_v67()
            manifest = _register_manifest()
            ready = bool(patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_EXIT_SUBMISSION_FAILURE_TRUTH_V336_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXIT_SUBMISSION_FAILURE_TRUTH_V336_%s marker=%s ready=%s "
            "terminal_failure_not_fill=true no_ack_not_fill=true immediate_empty_position_not_fill=true "
            "pending_reconciliation_preserved=true confirmed_fill_preserved=true tracker_truth_preserved=true "
            "forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook"]
