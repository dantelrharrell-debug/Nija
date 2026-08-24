"""Guard exchange rejection-rate kill switching against tiny samples (v222).

Production on 2026-08-24 proved the exchange rejection-rate gate could trip the
canonical global kill switch on the first rejected order: 1/1 = 100% >= 50%.
That is mathematically true but statistically insufficient to establish an
exchange rejection storm. The resulting EXCHANGE_MONITOR stop then persisted
across healthy runtime recovery and blocked the verification heartbeat itself.

v222 makes two narrow changes without bypassing safety controls:

1. The order-rejection RED gate requires a minimum sample count (default 5,
   bounded to [2, order_window_size]). Before that count, rejected samples are
   YELLOW/insufficient-sample diagnostics, never RED.
2. A lifetime recovery worker may clear only the exact historical
   EXCHANGE_MONITOR single-sample signature ``(1/1 orders rejected)`` and only
   after the exact writer/core is healthy and all non-stop structural readiness
   proofs are current. Manual/UI/CLI, drawdown, risk, authentication, balance,
   API-instability, unknown, and multi-sample exchange stops remain preserved.

After deactivation, authority/nonce/execution readiness must be re-earned by the
normal canonical runtime. This patch never marks those proofs, never forces
LIVE_ACTIVE, and never fabricates execution/order/fill evidence.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.exchange_rejection_sample_guard_v222")
MARKER = "20260824-exchange-rejection-sample-guard-v222"
_FLAG = "NIJA_EXCHANGE_REJECTION_SAMPLE_GUARD_V222_READY"
_PATCH_ATTR = "_nija_exchange_rejection_sample_guard_v222"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_RECOVERED = False


def _minimum_samples(cfg: Any) -> int:
    try:
        window = max(2, int(getattr(cfg, "order_window_size", 20) or 20))
    except Exception:
        window = 20
    try:
        requested = int(float(os.environ.get("NIJA_ORDER_REJECT_MIN_SAMPLES", "5") or "5"))
    except Exception:
        requested = 5
    return max(2, min(requested, window))


def _patch_rejection_gate() -> bool:
    module = importlib.import_module("bot.exchange_kill_switch")
    cls = getattr(module, "ExchangeKillSwitchProtector", None)
    gate_result = getattr(module, "GateResult", None)
    gate_status = getattr(module, "GateStatus", None)
    if not isinstance(cls, type) or gate_result is None or gate_status is None:
        return False

    current = getattr(cls, "_gate_order_rejection", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def guarded(self: Any):
        cfg = getattr(self, "_cfg", None)
        lock = getattr(self, "_lock", None)
        if cfg is None or lock is None:
            return current(self)
        try:
            with lock:
                results = list(getattr(self, "_order_results", ()))
        except Exception:
            return current(self)

        if not results:
            return current(self)

        total = len(results)
        rejected = sum(1 for item in results if not item)
        min_samples = _minimum_samples(cfg)
        if total < min_samples:
            rate = rejected / total
            detail = {
                "window_orders": total,
                "rejected": rejected,
                "rejection_rate_pct": round(rate * 100, 1),
                "minimum_samples_for_red": min_samples,
                "sample_sufficient": False,
            }
            if rejected:
                return gate_result(
                    "order_rejection",
                    gate_status.YELLOW,
                    f"Order rejection sample insufficient for RED: {rejected}/{total} rejected; "
                    f"need {min_samples} samples",
                    detail,
                )
            return gate_result(
                "order_rejection",
                gate_status.GREEN,
                f"Order rejection sample warming: 0/{total} rejected; need {min_samples} samples",
                detail,
            )

        result = current(self)
        try:
            if isinstance(getattr(result, "detail", None), dict):
                result.detail.setdefault("minimum_samples_for_red", min_samples)
                result.detail.setdefault("sample_sufficient", True)
        except Exception:
            pass
        return result

    setattr(guarded, _PATCH_ATTR, True)
    setattr(guarded, "__wrapped__", current)
    cls._gate_order_rejection = guarded
    return True


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
    history = list(status.get("recent_history") or [])
    for item in reversed(history):
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


def _exact_single_sample_stop(record: dict[str, Any]) -> tuple[bool, str]:
    source = str(record.get("source") or "").strip().upper()
    reason = str(record.get("reason") or "").strip()
    lowered = reason.lower()
    if source != "EXCHANGE_MONITOR":
        return False, f"source_not_exchange_monitor:{source or 'missing'}"
    required = (
        "exchange kill-switch: order rejection rate 100.0%",
        "(1/1 orders rejected)",
    )
    if not all(token in lowered for token in required):
        return False, "reason_not_exact_single_sample_rejection"
    forbidden = (
        "manual", "drawdown", "daily loss", "weekly loss", "invalid_credentials",
        "unauthorized", "invalid key", "signature", "balance delta", "api instability",
    )
    if any(token in lowered for token in forbidden):
        return False, "unsafe_reason_overlap"
    return True, reason[:512]


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
        getter = getattr(kill_module, "get_kill_switch", None)
        ks = getter() if callable(getter) else None
        if ks is None or not callable(getattr(ks, "get_status", None)):
            return False
        status = dict(ks.get_status() or {})
        if not bool(status.get("is_active")):
            return False

        record = _causal_record(status)
        signature_ok, signature_detail = _exact_single_sample_stop(record)
        if not signature_ok:
            LOGGER.info(
                "EXCHANGE_REJECTION_V222_RECOVERY_INELIGIBLE marker=%s detail=%s active_preserved=true",
                MARKER,
                signature_detail,
            )
            return False

        ready, ready_detail = _writer_and_structural_ready()
        if not ready:
            LOGGER.warning(
                "EXCHANGE_REJECTION_V222_RECOVERY_WAIT marker=%s blocker=%s active_preserved=true",
                MARKER,
                ready_detail,
            )
            return False

        deactivate = getattr(ks, "deactivate", None)
        if not callable(deactivate):
            return False
        result = deactivate("v222 verified recovery from legacy 1/1 exchange rejection sample latch")
        if result is False:
            LOGGER.critical(
                "EXCHANGE_REJECTION_V222_DEACTIVATE_REFUSED marker=%s trading_fail_closed=true",
                MARKER,
            )
            return False

        after = dict(ks.get_status() or {})
        if bool(after.get("is_active")) or bool(after.get("kill_file_exists")):
            LOGGER.critical(
                "EXCHANGE_REJECTION_V222_VERIFY_FAILED marker=%s active=%s marker_exists=%s trading_fail_closed=true",
                MARKER,
                str(bool(after.get("is_active"))).lower(),
                str(bool(after.get("kill_file_exists"))).lower(),
            )
            return False

        try:
            exchange_module = importlib.import_module("bot.exchange_kill_switch")
            protector_getter = getattr(exchange_module, "get_exchange_kill_switch_protector", None)
            protector = protector_getter() if callable(protector_getter) else None
            reset = getattr(protector, "reset", None)
            if callable(reset):
                reset("v222 cleared legacy single-sample rejection latch after verified recovery")
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECTION_V222_PROTECTOR_RESET_WARN marker=%s err=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )

        _RECOVERED = True
        LOGGER.critical(
            "EXCHANGE_REJECTION_V222_RECOVERED marker=%s causal_source=EXCHANGE_MONITOR "
            "legacy_single_sample=true causal_reason=%s writer_proof=exact structural_proofs=current "
            "authority_nonce_execution_not_fabricated=true activation_must_reprove=true "
            "forced_activation=false safety_gates_bypassed=false",
            MARKER,
            signature_detail,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "EXCHANGE_REJECTION_V222_RECOVERY_ERROR marker=%s err=%s:%s active_preserved=true trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        installers = getattr(manifest, "_INSTALLERS", None)
        if not isinstance(required, dict) or not isinstance(installers, tuple):
            return False
        required["exchange_rejection_sample_guard_v222"] = _FLAG
        own = ("bot.exchange_rejection_sample_guard_v222_patch", "install_import_hook")
        if own not in installers:
            manifest._INSTALLERS = tuple(installers) + (own,)
        return True
    except Exception:
        return False


def _worker() -> None:
    while True:
        try:
            _patch_rejection_gate()
            _register_manifest()
            attempt_recovery_once()
        except Exception as exc:
            LOGGER.warning(
                "EXCHANGE_REJECTION_V222_WORKER_ERROR marker=%s err=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(5.0)


def install() -> bool:
    global _THREAD
    if not _patch_rejection_gate():
        return False
    os.environ[_FLAG] = "1"
    _register_manifest()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="ExchangeRejectionSampleGuardV222",
                daemon=True,
            )
            _THREAD.start()
    LOGGER.critical(
        "EXCHANGE_REJECTION_SAMPLE_GUARD_V222_READY marker=%s ready=true min_samples=%d "
        "single_sample_red_blocked=true exact_legacy_recovery_only=true manual_ui_cli_risk_auth_unknown_preserved=true "
        "execution_authority_unchanged=true forced_activation=false safety_gates_bypassed=false",
        MARKER,
        _minimum_samples(getattr(importlib.import_module("bot.exchange_kill_switch").ExchangeKillSwitchProtector(), "_cfg", None)),
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "install", "install_import_hook", "attempt_recovery_once",
    "_minimum_samples", "_exact_single_sample_stop", "_writer_and_structural_ready",
]
