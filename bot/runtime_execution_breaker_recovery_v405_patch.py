"""Fail-closed recovery for a stale heartbeat-verification circuit-breaker latch.

Production can legitimately observe a stale execution verification sample and trip
its activation circuit breaker. Later, a genuine canonical execution proof can
become current again, while the old heartbeat-verification breaker remains
latched and continues rejecting normal activation attempts.

v405 clears *only* the heartbeat_verification breaker bucket, and only after:
- the canonical heartbeat/execution verification status is currently true,
- strict writer/nonce authority is currently true, and
- the kill switch is currently clear.

It does not extend freshness, change breaker thresholds, mark readiness, grant
execution authority, change trading state, write a proof marker, place/cancel an
order, or bypass any activation gate. Normal activation must still pass every
canonical gate after the stale latch is cleared.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_execution_breaker_recovery_v405")
MARKER = "20260908-runtime-execution-breaker-recovery-v405"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_BREAKER_RECOVERY_V405_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None


def _tsm() -> ModuleType:
    return importlib.import_module("bot.trading_state_machine")


def _kill_switch_clear() -> tuple[bool, str]:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        active = bool(get_kill_switch().is_active())
        return (not active), ("clear" if not active else "active")
    except Exception as exc:
        return False, f"probe_failed:{type(exc).__name__}:{exc}"


def _strict_writer_nonce_ready(tsm: ModuleType) -> tuple[bool, str]:
    probe = getattr(tsm, "_runtime_writer_nonce_ready", None)
    if not callable(probe):
        return False, "strict_probe_missing"
    try:
        ready, detail = probe()
        return bool(ready), str(detail or "")
    except Exception as exc:
        return False, f"strict_probe_failed:{type(exc).__name__}:{exc}"


def _verification_current(tsm: ModuleType) -> tuple[bool, str, dict[str, Any]]:
    probe = getattr(tsm, "_heartbeat_verification_status", None)
    if not callable(probe):
        return False, "verification_probe_missing", {}
    try:
        ready, detail, meta = probe()
        return bool(ready), str(detail or ""), dict(meta or {})
    except Exception as exc:
        return False, f"verification_probe_failed:{type(exc).__name__}:{exc}", {}


def _clear_recovered_heartbeat_latch_once() -> bool:
    tsm = _tsm()
    if not bool(getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_TRIPPED", False)):
        return False

    reason = str(getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "") or "")
    if "heartbeat_verification" not in reason.lower():
        return False

    verification_ready, verification_detail, verification_meta = _verification_current(tsm)
    if not verification_ready:
        return False

    authority_ready, authority_detail = _strict_writer_nonce_ready(tsm)
    if not authority_ready:
        return False

    kill_clear, kill_detail = _kill_switch_clear()
    if not kill_clear:
        return False

    lock = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_LOCK", None)
    counts = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_COUNTS", None)
    if lock is None or not isinstance(counts, dict):
        return False

    with lock:
        current_reason = str(getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "") or "")
        if "heartbeat_verification" not in current_reason.lower():
            return False

        prior_counts = dict(counts)
        for key in list(counts):
            if str(key or "").strip().lower() == "heartbeat_verification":
                counts.pop(key, None)

        # Never clear another breaker category. If any non-heartbeat breaker
        # remains, preserve the trip and let that safety condition stay authoritative.
        if counts:
            return False

        setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_TRIPPED", False)
        setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "")

    LOGGER.critical(
        "EXECUTION_BREAKER_RECOVERY_V405_CLEARED marker=%s prior_reason=%s prior_counts=%s "
        "verification_source=%s verification_age_s=%s writer_nonce=%s kill_switch=%s "
        "freshness_extended=false threshold_changed=false readiness_marked=false "
        "authority_granted=false trading_state_changed=false proof_written=false "
        "order_submitted=false order_cancelled=false forced_activation=false safety_gates_bypassed=false",
        MARKER,
        reason,
        prior_counts,
        str(verification_meta.get("verification_source") or verification_meta.get("source") or "primary"),
        str(verification_meta.get("age_s", "unknown")),
        authority_detail or "ready",
        kill_detail,
    )
    return True


def _worker() -> None:
    while True:
        try:
            _clear_recovered_heartbeat_latch_once()
        except Exception as exc:
            LOGGER.debug("v405 recovery pulse failed: %s", exc, exc_info=True)
        time.sleep(2.0)


def install() -> bool:
    global _THREAD
    with _LOCK:
        try:
            tsm = _tsm()
            required = all(
                hasattr(tsm, attr)
                for attr in (
                    "_heartbeat_verification_status",
                    "_runtime_writer_nonce_ready",
                    "_EXECUTION_CIRCUIT_BREAKER_LOCK",
                    "_EXECUTION_CIRCUIT_BREAKER_COUNTS",
                )
            )
            if not required:
                os.environ[_READY_FLAG] = "0"
                LOGGER.error("EXECUTION_BREAKER_RECOVERY_V405_NOT_READY marker=%s reason=tsm_contract_missing", MARKER)
                return False

            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = threading.Thread(
                    target=_worker,
                    name="ExecutionBreakerRecoveryV405",
                    daemon=True,
                )
                _THREAD.start()

            os.environ[_READY_FLAG] = "1"
            LOGGER.critical(
                "EXECUTION_BREAKER_RECOVERY_V405_READY marker=%s heartbeat_only=true "
                "fresh_verification_required=true strict_writer_nonce_required=true kill_switch_clear_required=true "
                "freshness_extended=false threshold_changed=false authority_granted=false state_changed=false "
                "orders_submitted=false orders_cancelled=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
            )
            return True
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "EXECUTION_BREAKER_RECOVERY_V405_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False


install_import_hook = install

__all__ = ["MARKER", "install", "install_import_hook", "_clear_recovered_heartbeat_latch_once"]
