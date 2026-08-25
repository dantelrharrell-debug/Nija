"""Recover a persisted historical multi-sample EXCHANGE_MONITOR rejection latch v226.

Production on 2026-08-24 proved a global stop with causal reason ``5/5 orders
rejected`` surviving into a new healthy runtime.  ExchangeKillSwitchProtector
persists its triggered flag/reason/history but does not persist the rolling
``_order_results`` deque.  Therefore a restarted process can inherit the old
trigger while having no current rejection samples with which to prove the storm
is still occurring.  The global hard stop then prevents the heartbeat order that
would otherwise establish fresh execution health.

v226 closes only that persisted-latch deadlock.  It may clear an EXCHANGE_MONITOR
multi-sample rejection stop once per process, and only when all of these are true:
* the causal source is exactly EXCHANGE_MONITOR;
* the reason is exactly an order-rejection-rate stop with rejected==total and
  total >= the configured minimum sample count;
* the ExchangeKillSwitchProtector is itself persisted-triggered with the same
  order-rejection reason;
* its current in-memory ``_order_results`` window is empty, proving the samples
  belong to a prior process rather than the current runtime;
* every non-order exchange-health gate is currently non-RED;
* the exact distributed writer/core is healthy;
* all non-stop structural readiness proofs are current.

Manual/UI/CLI, risk/drawdown, auth, balance, API-instability, unknown, mixed-rate,
and same-process rejection stops are preserved.  After deactivation the normal
heartbeat, nonce, authority, order and fill proofs must be re-earned.  A new real
5/5 storm in the same process cannot be auto-cleared because the current rolling
window is non-empty and the recovery is one-shot.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import threading
import time
from typing import Any

LOGGER = logging.getLogger("nija.exchange_rejection_stale_latch_v226")
MARKER = "20260824-exchange-rejection-stale-latch-v226"
_FLAG = "NIJA_EXCHANGE_REJECTION_STALE_LATCH_V226_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_RECOVERED = False
_PATTERN = re.compile(
    r"^Exchange kill-switch: Order rejection rate ([0-9]+(?:\.[0-9]+)?)%\s*[^\(]*\((\d+)/(\d+) orders rejected\)$",
    re.IGNORECASE,
)
_FORBIDDEN = (
    "manual", "operator", "ui", "cli", "drawdown", "daily loss", "weekly loss",
    "invalid_credentials", "unauthorized", "invalid key", "signature", "permission",
    "balance delta", "api instability", "phantom", "duplicate",
)


def _causal_record(status: dict[str, Any]) -> dict[str, Any]:
    try:
        v222 = importlib.import_module("bot.exchange_rejection_sample_guard_v222_patch")
        helper = getattr(v222, "_causal_record", None)
        if callable(helper):
            record = helper(status)
            if isinstance(record, dict):
                return record
    except Exception:
        pass
    return {}


def _minimum_samples(protector: Any) -> int:
    try:
        v222 = importlib.import_module("bot.exchange_rejection_sample_guard_v222_patch")
        helper = getattr(v222, "_minimum_samples", None)
        cfg = getattr(protector, "_cfg", None)
        if callable(helper):
            return int(helper(cfg))
    except Exception:
        pass
    return 5


def _exact_persisted_rejection_signature(record: dict[str, Any], protector: Any) -> tuple[bool, str]:
    source = str(record.get("source") or "").strip().upper()
    reason = str(record.get("reason") or "").strip()
    lowered = reason.lower()
    if source != "EXCHANGE_MONITOR":
        return False, f"source_not_exchange_monitor:{source or 'missing'}"
    if any(token in lowered for token in _FORBIDDEN):
        return False, "unsafe_reason_overlap"
    match = _PATTERN.match(reason)
    if match is None:
        return False, "reason_not_exact_rejection_rate"
    try:
        rate = float(match.group(1))
        rejected = int(match.group(2))
        total = int(match.group(3))
    except Exception:
        return False, "rejection_reason_parse_failed"
    minimum = _minimum_samples(protector)
    if total < minimum:
        return False, f"sample_below_multi_sample_minimum:{total}<{minimum}"
    if rejected != total or total <= 0 or rate < 99.9:
        return False, "not_full_rejection_storm_signature"
    return True, reason[:512]


def _protector_persisted_latch(protector: Any, causal_reason: str) -> tuple[bool, str]:
    try:
        status = dict(protector.get_status() or {})
    except Exception as exc:
        return False, f"protector_status_error:{type(exc).__name__}:{exc}"
    if not bool(status.get("triggered")):
        return False, "protector_not_triggered"
    trigger_reason = str(status.get("trigger_reason") or "").strip()
    if "order rejection" not in trigger_reason.lower():
        return False, "protector_trigger_not_order_rejection"
    # The protector's rolling order window is intentionally not persisted.  An
    # empty window while its persisted trigger is active is the key replay proof.
    lock = getattr(protector, "_lock", None)
    try:
        if lock is None:
            current_results = list(getattr(protector, "_order_results", ()) or ())
        else:
            with lock:
                current_results = list(getattr(protector, "_order_results", ()) or ())
    except Exception:
        return False, "current_order_window_unreadable"
    if current_results:
        return False, f"current_process_rejection_samples_present:{len(current_results)}"

    gates = list(status.get("gates") or [])
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        if str(gate.get("gate") or "").strip().lower() == "order_rejection":
            continue
        if str(gate.get("status") or "").strip().lower() == "red":
            return False, f"current_exchange_gate_red:{gate.get('gate') or 'unknown'}"
    return True, "persisted_trigger_empty_current_window_nonorder_gates_nonred"


def _writer_and_structural_ready() -> tuple[bool, str]:
    try:
        v219 = importlib.import_module("bot.kill_switch_false_auth_recovery_v219_patch")
        writer = getattr(v219, "_writer_healthy", None)
        structural = getattr(v219, "_structural_readiness", None)
        if not callable(writer) or not callable(structural):
            return False, "v219_readiness_helpers_missing"
        writer_ok, writer_detail = writer()
        if not writer_ok:
            return False, f"writer:{writer_detail}"
        structural_ok, structural_detail = structural()
        if not structural_ok:
            return False, f"structural:{structural_detail}"
        return True, "writer_and_structural_current"
    except Exception as exc:
        return False, f"readiness_probe_error:{type(exc).__name__}:{exc}"


def attempt_recovery_once() -> bool:
    global _RECOVERED
    if _RECOVERED:
        return False
    try:
        kill_module = importlib.import_module("bot.kill_switch")
        kill_getter = getattr(kill_module, "get_kill_switch", None)
        ks = kill_getter() if callable(kill_getter) else None
        if ks is None or not callable(getattr(ks, "get_status", None)):
            return False
        kill_status = dict(ks.get_status() or {})
        if not bool(kill_status.get("is_active")):
            return False

        exchange_module = importlib.import_module("bot.exchange_kill_switch")
        protector_getter = getattr(exchange_module, "get_exchange_kill_switch_protector", None)
        protector = protector_getter() if callable(protector_getter) else None
        if protector is None:
            return False

        record = _causal_record(kill_status)
        signature_ok, signature_detail = _exact_persisted_rejection_signature(record, protector)
        if not signature_ok:
            LOGGER.info(
                "EXCHANGE_REJECTION_STALE_LATCH_V226_INELIGIBLE marker=%s detail=%s active_preserved=true",
                MARKER,
                signature_detail,
            )
            return False

        persisted_ok, persisted_detail = _protector_persisted_latch(protector, signature_detail)
        if not persisted_ok:
            LOGGER.info(
                "EXCHANGE_REJECTION_STALE_LATCH_V226_INELIGIBLE marker=%s detail=%s active_preserved=true",
                MARKER,
                persisted_detail,
            )
            return False

        ready, ready_detail = _writer_and_structural_ready()
        if not ready:
            LOGGER.warning(
                "EXCHANGE_REJECTION_STALE_LATCH_V226_WAIT marker=%s blocker=%s active_preserved=true trading_fail_closed=true",
                MARKER,
                ready_detail,
            )
            return False

        deactivate = getattr(ks, "deactivate", None)
        if not callable(deactivate):
            return False
        result = deactivate(
            "v226 verified recovery from persisted EXCHANGE_MONITOR full-rejection latch after current health proof"
        )
        if result is False:
            LOGGER.critical(
                "EXCHANGE_REJECTION_STALE_LATCH_V226_DEACTIVATE_REFUSED marker=%s trading_fail_closed=true",
                MARKER,
            )
            return False
        after = dict(ks.get_status() or {})
        if bool(after.get("is_active")) or bool(after.get("kill_file_exists")):
            LOGGER.critical(
                "EXCHANGE_REJECTION_STALE_LATCH_V226_VERIFY_FAILED marker=%s active=%s marker_exists=%s trading_fail_closed=true",
                MARKER,
                str(bool(after.get("is_active"))).lower(),
                str(bool(after.get("kill_file_exists"))).lower(),
            )
            return False

        reset = getattr(protector, "reset", None)
        if callable(reset):
            reset("v226 cleared persisted rejection latch after canonical stop deactivation")

        _RECOVERED = True
        LOGGER.critical(
            "EXCHANGE_REJECTION_STALE_LATCH_V226_RECOVERED marker=%s causal_source=EXCHANGE_MONITOR "
            "persisted_replay_only=true current_order_window_empty=true one_shot=true "
            "causal_reason=%s current_exchange_nonorder_gates_nonred=true writer_proof=exact "
            "structural_proofs=current authority_nonce_execution_not_fabricated=true "
            "activation_must_reprove=true forced_activation=false safety_gates_bypassed=false",
            MARKER,
            signature_detail,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "EXCHANGE_REJECTION_STALE_LATCH_V226_ERROR marker=%s err=%s:%s active_preserved=true trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _register_manifest_if_loaded() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    except Exception:
        return True
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["exchange_rejection_stale_latch_v226"] = _FLAG
    own = ("bot.exchange_rejection_stale_latch_v226_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _worker() -> None:
    while True:
        try:
            _register_manifest_if_loaded()
            if attempt_recovery_once():
                return
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECTION_STALE_LATCH_V226_WORKER_ERROR marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(2.0)


def install() -> bool:
    global _THREAD
    manifest_ok = _register_manifest_if_loaded()
    if not manifest_ok:
        os.environ[_FLAG] = "0"
        return False
    os.environ[_FLAG] = "1"
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ExchangeRejectionStaleLatchV226",
                daemon=True,
            )
            _THREAD.start()
    LOGGER.critical(
        "EXCHANGE_REJECTION_STALE_LATCH_V226_READY marker=%s ready=true "
        "exchange_monitor_only=true full_rejection_multi_sample_only=true persisted_replay_only=true "
        "current_order_window_must_be_empty=true nonorder_exchange_gates_must_be_nonred=true "
        "writer_structural_proofs_required=true one_shot=true manual_risk_auth_unknown_preserved=true "
        "authority_nonce_execution_unchanged=true forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "install", "install_import_hook", "attempt_recovery_once",
    "_exact_persisted_rejection_signature", "_protector_persisted_latch",
    "_writer_and_structural_ready",
]
