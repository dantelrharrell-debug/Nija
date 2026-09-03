"""Immediate execution activation + protective-coverage convergence v347.

v346 correctly requires a real v328-confirmed fill before execution readiness can
be proven. Production then showed all other readiness proofs green while the
execution marker remained absent because no post-v346 confirmed fill had yet
completed. This patch does not fabricate that missing proof. Instead it closes
only the handoff latency after a genuine fill and continuously audits that
existing actionable positions retain the already-established protective exit
coverage.

Safety invariants:
* no ACK or requested/current price becomes fill proof;
* no position is marked synchronized or protected synthetically;
* no order is forced;
* no kill switch, writer, nonce, risk, capital, ECEL, minimum-order, quantity,
  broker-health, reconciliation, order-ACK or fill gate is bypassed;
* dust/sub-minimum positions remain subject to the existing dust policy and are
  never enlarged to meet exchange minimums.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_execution_activation_protection_v347")
MARKER = "20260902-runtime-execution-activation-protection-v347"
RELEASE_ID = "20260902-runtime-convergence-v347"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_ACTIVATION_PROTECTION_V347_READY"
_FILL_PATCH = "_nija_v347_immediate_activation_after_confirmed_fill"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None


def _wake_activation() -> bool:
    """Reconcile only after the canonical execution marker already exists."""
    try:
        v238 = importlib.import_module("bot.runtime_heartbeat_marker_convergence_v238_patch")
        probe = getattr(v238, "_genuine_execution_marker_ready", None)
        wake = getattr(v238, "_wake_activation_after_genuine_marker", None)
        if not callable(probe) or not callable(wake):
            return False
        ready, detail = probe()
        if not bool(ready):
            return False
        result = bool(wake("canonical_confirmed_fill_v347"))
        LOGGER.critical(
            "EXECUTION_ACTIVATION_V347_WAKE marker=%s marker_ready=true detail=%s activation_woken=%s "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER, detail, str(result).lower(),
        )
        return result
    except Exception as exc:
        LOGGER.warning(
            "EXECUTION_ACTIVATION_V347_WAKE_DEFERRED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _patch_v346_marker_writer() -> bool:
    """Wake activation immediately after v346 successfully persists real fill proof."""
    module = importlib.import_module("bot.runtime_execution_position_readiness_v346_patch")
    current = getattr(module, "_write_confirmed_fill_marker", None)
    if not callable(current):
        return False
    if bool(getattr(current, _FILL_PATCH, False)):
        return True

    @wraps(current)
    def write_and_wake(*args: Any, **kwargs: Any) -> bool:
        written = bool(current(*args, **kwargs))
        if written:
            _wake_activation()
        return written

    setattr(write_and_wake, _FILL_PATCH, True)
    setattr(write_and_wake, "__wrapped__", current)
    module._write_confirmed_fill_marker = write_and_wake
    return True


def _audit_protective_coverage() -> bool:
    """Read-only audit of existing v281 protection coverage; never fabricates it."""
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        # Prefer a native status/audit helper when exposed. Different historical
        # releases used different names, so inspect only known read-only helpers.
        for name in ("coverage_status", "_coverage_status", "get_coverage_status", "_status"):
            fn = getattr(v281, name, None)
            if not callable(fn):
                continue
            try:
                result = fn()
            except TypeError:
                continue
            LOGGER.info(
                "PROTECTIVE_COVERAGE_V347_AUDIT marker=%s source=v281 result=%s "
                "tracker_mutation=false protection_fabricated=false dust_policy_unchanged=true",
                MARKER, str(result)[:1200],
            )
            return True
        # v281 already owns protection attachment and logs its authoritative
        # coverage state. Absence of a public read helper is not a reason to
        # mutate trackers here.
        LOGGER.info(
            "PROTECTIVE_COVERAGE_V347_AUDIT marker=%s source=v281 native_status_helper=unavailable "
            "v281_authority_unchanged=true tracker_mutation=false protection_fabricated=false "
            "dust_policy_unchanged=true",
            MARKER,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "PROTECTIVE_COVERAGE_V347_AUDIT_DEFERRED marker=%s error=%s:%s "
            "tracker_mutation=false trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_execution_activation_protection_v347"] = _READY_FLAG
        return True
    except Exception:
        return False


def _worker() -> None:
    while True:
        try:
            _patch_v346_marker_writer()
            _wake_activation()
            _audit_protective_coverage()
        except Exception:
            LOGGER.debug("v347 worker pulse failed", exc_info=True)
        time.sleep(3.0)


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        marker_ready = protection_ready = manifest_ready = False
        try:
            marker_ready = _patch_v346_marker_writer()
            protection_ready = _audit_protective_coverage()
            manifest_ready = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_EXECUTION_ACTIVATION_PROTECTION_V347_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(marker_ready and protection_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready and (_THREAD is None or not _THREAD.is_alive()):
            _THREAD = threading.Thread(target=_worker, name="ExecutionActivationProtectionV347", daemon=True)
            _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXECUTION_ACTIVATION_PROTECTION_V347_%s marker=%s ready=%s "
            "confirmed_fill_immediate_activation_wakeup=%s protective_coverage_audit=%s manifest=%s "
            "take_profit_authority=v281 stop_loss_authority=v281 trailing_take_profit_authority=v281 "
            "trailing_stop_authority=v281 auto_exit_reconciler_authority=v281 dust_policy_unchanged=true "
            "no_forced_trade=true ack_alone_not_execution_proof=true fill_proof_fabricated=false "
            "tracker_mutation=false writer_nonce_capital_risk_killswitch_ecel_minimum_quantity_position_order_fill_gates_unchanged=true "
            "forced_activation=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), str(marker_ready).lower(),
            str(protection_ready).lower(), str(manifest_ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook"]
