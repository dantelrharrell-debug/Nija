"""Recover a stale historical EXCHANGE_MONITOR rejection latch v226.

Production on 2026-08-24 showed the root rejection-feedback bug already repaired
by v224, but a historical global stop remained active with the exact reason
``Exchange kill-switch: Order rejection rate 100.0% (5/5 orders rejected)``.
V222 correctly refuses to clear multi-sample stops, so the repaired runtime has
no path to re-earn authority: the active stop blocks the heartbeat and the
heartbeat cannot produce a new accepted order while the stop is active.

v226 adds a deliberately narrow, guarded recovery for this legacy deadlock.  It
may deactivate only an EXCHANGE_MONITOR order-rejection stop whose reason has a
parseable rejected/total sample with rejected == total and total >= 2, and only
after:
* v224 is installed, so local hard-stop blocks cannot keep poisoning telemetry;
* the exact distributed writer lease and core thread are healthy;
* all structural proofs except capital/authority/nonce/execution are current;
* no real current exchange-health gate other than order_rejection is RED;
* the current in-memory order window is empty, proving the historical 5/5
  sample itself is not present in the new process.

Capital is intentionally not required because the same production incident also
showed a separate capital-publication representation bug; capital must still be
re-earned normally after the stop clears.  Manual/UI/CLI, risk/drawdown, auth,
API-instability, price, latency, phantom-fill, duplicate-order, unknown, mixed
accepted/rejected, and current-window rejection stops are preserved.

This patch never marks readiness, resets a current rejection window, fabricates
an accepted order/fill, grants execution authority, or forces LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.exchange_rejection_stale_latch_recovery_v226")
MARKER = "20260824-exchange-rejection-stale-latch-recovery-v226"
_FLAG = "NIJA_EXCHANGE_REJECTION_STALE_LATCH_RECOVERY_V226_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_RECOVERED = False
_SAMPLE_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\s+orders?\s+rejected\)", re.IGNORECASE)

_FORBIDDEN_REASON_TOKENS = (
    "manual", "ui", "cli", "operator", "drawdown", "daily loss", "weekly loss",
    "balance delta", "unexpected balance", "invalid_credentials", "unauthorized",
    "invalid key", "invalid signature", "permission denied", "api instability",
    "phantom", "duplicate", "price spike", "stale price", "latency",
)
_STRUCTURAL_REQUIRED = (
    "broker_connected",
    "balance_hydrated",
    "risk_ready",
    "strategy_ready",
    "bootstrap_ready",
    "position_sync_ready",
)


def _v224_ready() -> bool:
    return str(os.environ.get("NIJA_EXCHANGE_REJECT_PROVENANCE_V224_READY", "")).strip().lower() in {
        "1", "true", "yes", "on"
    }


def _causal_record(status: dict[str, Any]) -> dict[str, Any]:
    try:
        v219 = importlib.import_module("bot.kill_switch_false_auth_recovery_v219_patch")
        helper = getattr(v219, "_causal_record", None)
        if callable(helper):
            record = helper(status)
            if isinstance(record, dict):
                return record
    except Exception:
        pass
    for item in reversed(list(status.get("recent_history") or [])):
        if not isinstance(item, dict):
            return {}
        source = str(item.get("source") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if source.upper() == "FILE_SYSTEM" and "kill switch file detected" in reason.lower():
            continue
        if source:
            return {"source": source, "reason": reason}
        return {}
    return {}


def _legacy_full_rejection_signature(record: dict[str, Any]) -> tuple[bool, str, int]:
    source = str(record.get("source") or "").strip().upper()
    reason = str(record.get("reason") or "").strip()
    lowered = reason.lower()
    if source != "EXCHANGE_MONITOR":
        return False, f"source_not_exchange_monitor:{source or 'missing'}", 0
    if "exchange kill-switch: order rejection rate" not in lowered:
        return False, "reason_not_order_rejection", 0
    if any(token in lowered for token in _FORBIDDEN_REASON_TOKENS):
        return False, "unsafe_reason_overlap", 0
    match = _SAMPLE_RE.search(reason)
    if match is None:
        return False, "sample_unparseable", 0
    rejected = int(match.group(1))
    total = int(match.group(2))
    if total < 2 or rejected != total:
        return False, f"not_full_multisample_rejection:{rejected}/{total}", total
    return True, reason[:512], total


def _writer_healthy() -> tuple[bool, str]:
    try:
        v219 = importlib.import_module("bot.kill_switch_false_auth_recovery_v219_patch")
        helper = getattr(v219, "_writer_healthy", None)
        if not callable(helper):
            return False, "v219_writer_helper_missing"
        ok, detail = helper()
        return bool(ok), str(detail)
    except Exception as exc:
        return False, f"writer_probe_error:{type(exc).__name__}:{exc}"


def _structural_ready() -> tuple[bool, str]:
    try:
        table = importlib.import_module("bot.readiness_table")
        snapshot = dict(table.snapshot() or {})
    except Exception as exc:
        return False, f"readiness_probe_error:{type(exc).__name__}:{exc}"
    missing = [name for name in _STRUCTURAL_REQUIRED if not bool(snapshot.get(name, False))]
    if missing:
        return False, "structural_pending:" + ",".join(missing)
    return True, "noncapital_structural_proofs_current"


def _exchange_health_safe_for_reprobe() -> tuple[bool, str, Any]:
    try:
        module = importlib.import_module("bot.exchange_kill_switch")
        getter = getattr(module, "get_exchange_kill_switch_protector", None)
        protector = getter() if callable(getter) else None
        if protector is None:
            return False, "exchange_protector_missing", None

        lock = getattr(protector, "_lock", None)
        if lock is None:
            return False, "exchange_protector_lock_missing", protector
        with lock:
            current_orders = list(getattr(protector, "_order_results", ()))
        if current_orders:
            return False, f"current_order_window_not_empty:{len(current_orders)}", protector

        evaluate = getattr(protector, "evaluate_all_gates", None)
        if not callable(evaluate):
            return False, "gate_evaluator_missing", protector
        gates = list(evaluate() or [])
        red = []
        for gate in gates:
            status = str(getattr(getattr(gate, "status", None), "value", getattr(gate, "status", ""))).lower()
            name = str(getattr(gate, "gate_name", "") or "").lower()
            if status == "red" and name != "order_rejection":
                red.append(name or "unknown")
        if red:
            return False, "current_exchange_red_gates:" + ",".join(sorted(set(red))), protector
        return True, "new_process_exchange_window_empty_other_gates_nonred", protector
    except Exception as exc:
        return False, f"exchange_health_probe_error:{type(exc).__name__}:{exc}", None


def attempt_recovery_once() -> bool:
    global _RECOVERED
    if _RECOVERED or not _v224_ready():
        return False
    try:
        kill_module = importlib.import_module("bot.kill_switch")
        getter = getattr(kill_module, "get_kill_switch", None)
        ks = getter() if callable(getter) else None
        if ks is None or not callable(getattr(ks, "get_status", None)):
            return False
        status = dict(ks.get_status() or {})
        if not bool(status.get("is_active")):
            return False

        record = _causal_record(status)
        signature_ok, signature_detail, sample_count = _legacy_full_rejection_signature(record)
        if not signature_ok:
            return False

        writer_ok, writer_detail = _writer_healthy()
        if not writer_ok:
            LOGGER.warning(
                "EXCHANGE_REJECTION_V226_WAIT marker=%s blocker=writer:%s active_preserved=true",
                MARKER, writer_detail,
            )
            return False

        structural_ok, structural_detail = _structural_ready()
        if not structural_ok:
            LOGGER.warning(
                "EXCHANGE_REJECTION_V226_WAIT marker=%s blocker=%s active_preserved=true",
                MARKER, structural_detail,
            )
            return False

        health_ok, health_detail, protector = _exchange_health_safe_for_reprobe()
        if not health_ok:
            LOGGER.warning(
                "EXCHANGE_REJECTION_V226_WAIT marker=%s blocker=%s active_preserved=true",
                MARKER, health_detail,
            )
            return False

        deactivate = getattr(ks, "deactivate", None)
        if not callable(deactivate):
            return False
        result = deactivate(
            "v226 verified recovery from stale historical full-rejection EXCHANGE_MONITOR latch; live heartbeat must reprove execution"
        )
        if result is False:
            LOGGER.critical(
                "EXCHANGE_REJECTION_V226_DEACTIVATE_REFUSED marker=%s trading_fail_closed=true",
                MARKER,
            )
            return False

        after = dict(ks.get_status() or {})
        if bool(after.get("is_active")) or bool(after.get("kill_file_exists")):
            LOGGER.critical(
                "EXCHANGE_REJECTION_V226_VERIFY_FAILED marker=%s active=%s marker_exists=%s trading_fail_closed=true",
                MARKER,
                str(bool(after.get("is_active"))).lower(),
                str(bool(after.get("kill_file_exists"))).lower(),
            )
            return False

        # Clear only the protector's historical triggered metadata after the
        # canonical global stop has transactionally cleared. The current order
        # window was proven empty above, so no current exchange evidence is lost.
        reset = getattr(protector, "reset", None)
        if callable(reset):
            reset("v226 stale historical rejection latch cleared; current window was empty")

        _RECOVERED = True
        LOGGER.critical(
            "EXCHANGE_REJECTION_V226_RECOVERED marker=%s causal_source=EXCHANGE_MONITOR "
            "historical_full_rejection_sample=%d current_order_window_empty=true "
            "other_exchange_red_gates=false v224_provenance_guard=true writer_proof=exact "
            "structural_noncapital_proofs=current capital_must_reprove=true "
            "authority_nonce_execution_not_fabricated=true heartbeat_must_reprove=true "
            "forced_activation=false safety_gates_bypassed=false causal_reason=%s",
            MARKER,
            sample_count,
            signature_detail,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "EXCHANGE_REJECTION_V226_RECOVERY_ERROR marker=%s err=%s:%s "
            "active_preserved=true trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _register_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch")
    if not isinstance(manifest, ModuleType):
        return True
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["exchange_rejection_stale_latch_recovery_v226"] = _FLAG
    own = ("bot.exchange_rejection_stale_latch_recovery_v226_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _worker() -> None:
    deadline = time.monotonic() + 300.0
    while time.monotonic() < deadline:
        try:
            _register_manifest()
            if attempt_recovery_once():
                return
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECTION_V226_WORKER_ERROR marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(2.0)


def install() -> bool:
    global _THREAD
    os.environ[_FLAG] = "1"
    _register_manifest()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ExchangeRejectionStaleLatchRecoveryV226",
                daemon=True,
            )
            _THREAD.start()
    LOGGER.critical(
        "EXCHANGE_REJECTION_STALE_LATCH_RECOVERY_V226_READY marker=%s ready=true "
        "legacy_exchange_monitor_full_rejection_only=true current_window_must_be_empty=true "
        "other_exchange_red_gates_block=true exact_writer_required=true "
        "structural_noncapital_proofs_required=true capital_authority_nonce_execution_must_reprove=true "
        "manual_risk_auth_api_unknown_preserved=true forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "attempt_recovery_once",
    "_legacy_full_rejection_signature",
    "_exchange_health_safe_for_reprobe",
]
