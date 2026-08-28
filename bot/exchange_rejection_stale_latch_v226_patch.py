"""Recover verified stale EXCHANGE_MONITOR rejection latches (v226/v267).

v226 recovers a persisted full-rejection latch only when the current process has
no rejection samples. v267 adds a second, deliberately narrow path for the
production deadlock where the current process contains rejection samples that
can all be proven, from recorder provenance, to be local/pre-dispatch outcomes
that are now classified as non-exchange failures.

Safety invariants:
* only an exact EXCHANGE_MONITOR 100% multi-sample rejection stop is eligible;
* manual/UI/CLI, risk/drawdown, auth, balance, API-instability and unknown stops
  are preserved;
* the current rejection deque is never cleared unless every sample is rejected
  and every corresponding provenance record is positively classified as
  non-exchange by the live v258 classifier;
* unknown or genuine exchange rejections preserve the stop;
* all non-order exchange gates must be non-RED;
* exact writer/core and structural readiness proofs must be current;
* recovery is one-shot and normal heartbeat/nonce/authority/order/fill proofs
  must be re-earned afterwards.
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
V267_MARKER = "20260828-current-rejection-provenance-recovery-v267"
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


def _nonorder_gates_nonred(status: dict[str, Any]) -> tuple[bool, str]:
    for gate in list(status.get("gates") or []):
        if not isinstance(gate, dict):
            continue
        if str(gate.get("gate") or "").strip().lower() == "order_rejection":
            continue
        if str(gate.get("status") or "").strip().lower() == "red":
            return False, f"current_exchange_gate_red:{gate.get('gate') or 'unknown'}"
    return True, "current_exchange_nonorder_gates_nonred"


def _read_current_results(protector: Any) -> tuple[bool, list[bool] | str]:
    lock = getattr(protector, "_lock", None)
    try:
        if lock is None:
            results = list(getattr(protector, "_order_results", ()) or ())
        else:
            with lock:
                results = list(getattr(protector, "_order_results", ()) or ())
        return True, [bool(value) for value in results]
    except Exception:
        return False, "current_order_window_unreadable"


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
    readable, payload = _read_current_results(protector)
    if not readable:
        return False, str(payload)
    current_results = payload if isinstance(payload, list) else []
    if current_results:
        return False, f"current_process_rejection_samples_present:{len(current_results)}"
    return _nonorder_gates_nonred(status)


def _current_window_false_positive_proof(protector: Any) -> tuple[bool, str, int]:
    """Prove that every current rejection sample is local/non-exchange.

    The core protector stores only booleans. v258 separately stores bounded
    per-result provenance. We require an exact tail alignment: the last N
    provenance records must have accepted values matching the N current window
    booleans, all N booleans must be False, and every matched reason must be
    positively classified by the *current* v258 classifier. This deliberately
    rejects ambiguous histories rather than guessing.
    """
    try:
        status = dict(protector.get_status() or {})
    except Exception as exc:
        return False, f"protector_status_error:{type(exc).__name__}:{exc}", 0
    if not bool(status.get("triggered")):
        return False, "protector_not_triggered", 0
    trigger_reason = str(status.get("trigger_reason") or "").strip().lower()
    if "order rejection" not in trigger_reason:
        return False, "protector_trigger_not_order_rejection", 0
    gates_ok, gates_detail = _nonorder_gates_nonred(status)
    if not gates_ok:
        return False, gates_detail, 0

    readable, payload = _read_current_results(protector)
    if not readable:
        return False, str(payload), 0
    results = payload if isinstance(payload, list) else []
    minimum = _minimum_samples(protector)
    if len(results) < minimum:
        return False, f"current_window_below_minimum:{len(results)}<{minimum}", 0
    if any(results):
        return False, "current_window_contains_accepted_samples", 0

    history = getattr(protector, "_nija_order_result_provenance_v258", None)
    try:
        records = list(history or ())
    except Exception:
        return False, "provenance_history_unreadable", 0
    if len(records) < len(results):
        return False, f"provenance_history_short:{len(records)}<{len(results)}", 0

    tail = records[-len(results):]
    accepted_tail = [bool(item.get("accepted")) if isinstance(item, dict) else True for item in tail]
    if accepted_tail != results:
        return False, "provenance_tail_not_aligned_with_current_window", 0

    try:
        v258 = importlib.import_module("bot.exchange_kill_switch_alias_provenance_v258_patch")
        classifier = getattr(v258, "_is_non_exchange", None)
    except Exception:
        classifier = None
    if not callable(classifier):
        return False, "v258_classifier_missing", 0

    for index, item in enumerate(tail):
        if not isinstance(item, dict):
            return False, f"provenance_record_invalid:{index}", 0
        reason = str(item.get("reason") or "").strip()
        source = str(item.get("source") or "").strip()
        if source != "execution_pipeline":
            return False, f"provenance_source_not_execution_pipeline:{index}:{source or 'missing'}", 0
        if not reason:
            return False, f"provenance_reason_missing:{index}", 0
        if not bool(classifier(reason)):
            return False, f"provenance_not_non_exchange:{index}:{reason[:160]}", 0

    return True, f"verified_non_exchange_current_window:{len(results)}", len(results)


def _clear_verified_current_window(protector: Any, expected_count: int) -> tuple[bool, str]:
    lock = getattr(protector, "_lock", None)
    try:
        if lock is None:
            results = getattr(protector, "_order_results", None)
            if results is None or len(results) != expected_count or any(bool(v) for v in results):
                return False, "current_window_changed_before_clear"
            results.clear()
        else:
            with lock:
                results = getattr(protector, "_order_results", None)
                if results is None or len(results) != expected_count or any(bool(v) for v in results):
                    return False, "current_window_changed_before_clear"
                results.clear()
        return True, f"verified_current_window_cleared:{expected_count}"
    except Exception as exc:
        return False, f"verified_current_window_clear_error:{type(exc).__name__}:{exc}"


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
            LOGGER.info("EXCHANGE_REJECTION_STALE_LATCH_V226_INELIGIBLE marker=%s detail=%s active_preserved=true", MARKER, signature_detail)
            return False

        persisted_ok, persisted_detail = _protector_persisted_latch(protector, signature_detail)
        recovery_mode = "persisted_empty_window"
        verified_count = 0
        if not persisted_ok:
            if not str(persisted_detail).startswith("current_process_rejection_samples_present:"):
                LOGGER.info("EXCHANGE_REJECTION_STALE_LATCH_V226_INELIGIBLE marker=%s detail=%s active_preserved=true", MARKER, persisted_detail)
                return False
            proven, proof_detail, verified_count = _current_window_false_positive_proof(protector)
            if not proven:
                LOGGER.warning(
                    "CURRENT_REJECTION_PROVENANCE_V267_PRESERVED marker=%s detail=%s active_preserved=true trading_fail_closed=true",
                    V267_MARKER,
                    proof_detail,
                )
                return False
            recovery_mode = "verified_current_non_exchange_window"

        ready, ready_detail = _writer_and_structural_ready()
        if not ready:
            LOGGER.warning("EXCHANGE_REJECTION_STALE_LATCH_V226_WAIT marker=%s blocker=%s active_preserved=true trading_fail_closed=true", MARKER, ready_detail)
            return False

        if recovery_mode == "verified_current_non_exchange_window":
            cleared, clear_detail = _clear_verified_current_window(protector, verified_count)
            if not cleared:
                LOGGER.warning(
                    "CURRENT_REJECTION_PROVENANCE_V267_CLEAR_REFUSED marker=%s detail=%s active_preserved=true trading_fail_closed=true",
                    V267_MARKER,
                    clear_detail,
                )
                return False
            LOGGER.critical(
                "CURRENT_REJECTION_PROVENANCE_V267_RECLASSIFIED marker=%s samples=%d exact_tail_alignment=true "
                "all_samples_non_exchange=true rejection_thresholds_unchanged=true genuine_exchange_rejects_preserved=true "
                "manual_risk_auth_unknown_preserved=true safety_gates_bypassed=false",
                V267_MARKER,
                verified_count,
            )

        deactivate = getattr(ks, "deactivate", None)
        if not callable(deactivate):
            return False
        result = deactivate(
            "v226/v267 verified recovery from EXCHANGE_MONITOR full-rejection latch after current health and provenance proof"
        )
        if result is False:
            LOGGER.critical("EXCHANGE_REJECTION_STALE_LATCH_V226_DEACTIVATE_REFUSED marker=%s trading_fail_closed=true", MARKER)
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
            reset("v226/v267 cleared verified rejection latch after canonical stop deactivation")

        _RECOVERED = True
        LOGGER.critical(
            "EXCHANGE_REJECTION_STALE_LATCH_V226_RECOVERED marker=%s v267_marker=%s causal_source=EXCHANGE_MONITOR "
            "recovery_mode=%s one_shot=true causal_reason=%s current_exchange_nonorder_gates_nonred=true "
            "writer_proof=exact structural_proofs=current authority_nonce_execution_not_fabricated=true "
            "activation_must_reprove=true forced_activation=false safety_gates_bypassed=false",
            MARKER,
            V267_MARKER,
            recovery_mode,
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
            _THREAD = threading.Thread(target=_worker, name="ExchangeRejectionStaleLatchV226", daemon=True)
            _THREAD.start()
    LOGGER.critical(
        "EXCHANGE_REJECTION_STALE_LATCH_V226_READY marker=%s v267_marker=%s ready=true "
        "exchange_monitor_only=true full_rejection_multi_sample_only=true persisted_replay_only=false "
        "current_window_requires_exact_provenance=true nonorder_exchange_gates_must_be_nonred=true "
        "writer_structural_proofs_required=true one_shot=true manual_risk_auth_unknown_preserved=true "
        "authority_nonce_execution_unchanged=true forced_activation=false safety_gates_bypassed=false",
        MARKER,
        V267_MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "V267_MARKER", "install", "install_import_hook", "attempt_recovery_once",
    "_exact_persisted_rejection_signature", "_protector_persisted_latch",
    "_current_window_false_positive_proof", "_clear_verified_current_window",
    "_writer_and_structural_ready",
]
