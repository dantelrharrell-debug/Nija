"""Converge platform position proof and nonce-lease activation liveness.

v163 keeps all existing fail-closed requirements, but removes two startup
liveness contradictions observed on 2026-08-19:

* a platform broker is not position-ready until both the adopted marker and the
  independent authoritative-fetch proof are true;
* a same-owner/same-token lease that is merely completing its configured
  stability window remains an activation deferral, not a nonce-drift anomaly.

The full nonce stability duration, lease identity, Redis/writer authority,
position fetch proof, circuit breakers for real faults, and every trading/risk
safety gate remain required.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_activation_convergence_v163")
MARKER = "20260819-runtime-activation-convergence-v163"
_READY_FLAG = "NIJA_RUNTIME_ACTIVATION_CONVERGENCE_V163_READY"
_PATCH_ATTR = "_nija_runtime_activation_convergence_v163"
_LOCK = threading.RLock()


def _v108() -> ModuleType:
    return importlib.import_module("bot.platform_position_sync_v108_patch")


def _v161() -> ModuleType:
    return importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")


def _tsm() -> ModuleType:
    return importlib.import_module("bot.trading_state_machine")


def _v155() -> ModuleType:
    return importlib.import_module("bot.nonce_lease_maturity_v155_patch")


def _connected_platform_brokers_requiring_proof(manager: Any) -> list[tuple[str, Any]]:
    """Find connected platform brokers missing either authoritative sync proof."""
    found: list[tuple[str, Any]] = []
    try:
        platform = getattr(manager, "platform_brokers", {}) or {}
        if callable(platform):
            platform = platform()
        for broker_type, broker in dict(platform or {}).items():
            if broker is None or not bool(getattr(broker, "connected", False)):
                continue
            adopted = bool(getattr(broker, "_startup_position_sync_adopted", False))
            fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None) is True
            if adopted and fetch_ok:
                continue
            name = str(getattr(broker_type, "value", broker_type) or "unknown").lower()
            found.append((name, broker))
    except Exception as exc:
        LOGGER.warning(
            "POSITION_SYNC_V163_DISCOVERY_FAILED marker=%s error=%s:%s fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
    return found


def _position_worker_v163(
    manager: Any,
    broker_name: str,
    broker: Any,
    key: tuple[int, int],
    trigger: str,
) -> None:
    """Retry authoritative adoption until BOTH adopted and fetch proof are true."""
    v108 = _v108()
    v161 = _v161()
    try:
        sync_module = v161._startup_sync_module()
        get_eps = getattr(sync_module, "_get_entry_price_store", None)
        eps = get_eps() if callable(get_eps) else None
        adopt = getattr(sync_module, "_adopt_broker_positions", None)
        if not callable(adopt):
            raise RuntimeError("startup position-sync adopter unavailable")
        max_attempts, base_delay_s, max_delay_s = v108._retry_policy()
        LOGGER.critical(
            "POSITION_SYNC_V163_START marker=%s broker=%s trigger=%s max_attempts=%d "
            "adopted_and_fetch_proof_required=true synthetic_success=false",
            MARKER,
            broker_name,
            trigger,
            max_attempts,
        )
        for attempt in range(1, max_attempts + 1):
            attempt_error: BaseException | None = None
            try:
                adopt(broker, f"platform:{broker_name}", eps)
            except Exception as exc:
                attempt_error = exc
                setattr(broker, "_startup_position_sync_adopted", False)
                setattr(broker, "_startup_position_sync_fetch_ok", False)
                setattr(broker, "_startup_position_sync_error", f"{type(exc).__name__}:{exc}")

            adopted = bool(getattr(broker, "_startup_position_sync_adopted", False))
            fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None) is True
            error = getattr(broker, "_startup_position_sync_error", None)
            v108._publish_readiness(manager, source=f"v163:{trigger}:{broker_name}:attempt_{attempt}")
            if adopted and fetch_ok:
                LOGGER.critical(
                    "POSITION_SYNC_V163_COMPLETE marker=%s broker=%s trigger=%s attempt=%d "
                    "adopted=true fetch_ok=true error=%s",
                    MARKER,
                    broker_name,
                    trigger,
                    attempt,
                    error,
                )
                return
            if attempt >= max_attempts:
                LOGGER.warning(
                    "POSITION_SYNC_V163_RETRIES_EXHAUSTED marker=%s broker=%s trigger=%s attempts=%d "
                    "adopted=%s fetch_ok=%s error=%s last_exception=%s trading_fail_closed=true",
                    MARKER,
                    broker_name,
                    trigger,
                    max_attempts,
                    str(adopted).lower(),
                    str(fetch_ok).lower(),
                    error,
                    type(attempt_error).__name__ if attempt_error is not None else "none",
                )
                return
            delay_s = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            time.sleep(delay_s)
    except BaseException as exc:
        try:
            setattr(broker, "_startup_position_sync_adopted", False)
            setattr(broker, "_startup_position_sync_fetch_ok", False)
            setattr(broker, "_startup_position_sync_error", f"{type(exc).__name__}:{exc}")
        except Exception:
            pass
        LOGGER.warning(
            "POSITION_SYNC_V163_FAILED marker=%s broker=%s trigger=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            broker_name,
            trigger,
            type(exc).__name__,
            exc,
        )
    finally:
        try:
            v108._publish_readiness(manager, source=f"v163:{trigger}:{broker_name}:final")
        except Exception:
            pass
        active = getattr(v108, "_ACTIVE", None)
        lock = getattr(v108, "_LOCK", None)
        if isinstance(active, set) and lock is not None:
            with lock:
                active.discard(key)


def _patch_position_sync() -> bool:
    v108 = _v108()
    discovery = getattr(v108, "_connected_unsynced_platform_brokers", None)
    worker = getattr(v108, "_worker", None)
    if not callable(discovery) or not callable(worker):
        return False
    if not bool(getattr(discovery, _PATCH_ATTR, False)):
        original_discovery = discovery

        @wraps(original_discovery)
        def discovery_v163(manager: Any) -> list[tuple[str, Any]]:
            return _connected_platform_brokers_requiring_proof(manager)

        setattr(discovery_v163, _PATCH_ATTR, True)
        setattr(discovery_v163, "__wrapped__", original_discovery)
        v108._connected_unsynced_platform_brokers = discovery_v163
    if not bool(getattr(worker, _PATCH_ATTR, False)):
        original_worker = worker

        @wraps(original_worker)
        def worker_v163(manager: Any, broker_name: str, broker: Any, key: tuple[int, int], trigger: str) -> None:
            _position_worker_v163(manager, broker_name, broker, key, trigger)

        setattr(worker_v163, _PATCH_ATTR, True)
        setattr(worker_v163, "__wrapped__", original_worker)
        v108._worker = worker_v163
    return True


def _transient_nonce_maturity(detail: str) -> bool:
    """True only for an ordinary same-lease maturity deferral."""
    text = str(detail or "").lower()
    if "nonce lease unstable" not in text:
        return False
    hard_markers = (
        "lease_identity_changed",
        "stability_regressed",
        "invalid_status",
        "status_unavailable",
        "incomplete_identity",
        "final_verify_error",
    )
    return not any(marker in text for marker in hard_markers)


def _clear_historical_maturity_breaker(tsm: ModuleType) -> bool:
    """Clear only a breaker whose recorded reason is transient lease maturity."""
    lock = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_LOCK", None)
    counts = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_COUNTS", None)
    reason = str(getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "") or "")
    if not bool(getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_TRIPPED", False)):
        return False
    if not _transient_nonce_maturity(reason) or lock is None or not isinstance(counts, dict):
        return False
    with lock:
        current_reason = str(getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "") or "")
        if not bool(getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_TRIPPED", False)):
            return False
        if not _transient_nonce_maturity(current_reason):
            return False
        counts.pop("nonce_drift", None)
        setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_TRIPPED", False)
        setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "")
    LOGGER.critical(
        "NONCE_V163_TRANSIENT_MATURITY_BREAKER_CLEARED marker=%s full_nonce_gate_verified=true "
        "unrelated_breakers_unchanged=true",
        MARKER,
    )
    return True


def _patch_nonce_convergence() -> bool:
    tsm = _tsm()
    v155 = _v155()
    cap = getattr(v155, "_final_wait_cap_s", None)
    record = getattr(tsm, "_record_execution_anomaly", None)
    gate = getattr(tsm, "_nonce_writer_lease_gate", None)
    if not callable(cap) or not callable(record) or not callable(gate):
        return False

    if not bool(getattr(cap, _PATCH_ATTR, False)):
        original_cap = cap

        @wraps(original_cap)
        def final_wait_cap_v163() -> float:
            # v155 itself has a five-second safety ceiling. Raising the old
            # two-second cap does not lower the configured maturity requirement.
            return 5.0

        setattr(final_wait_cap_v163, _PATCH_ATTR, True)
        setattr(final_wait_cap_v163, "__wrapped__", original_cap)
        v155._final_wait_cap_s = final_wait_cap_v163

    if not bool(getattr(record, _PATCH_ATTR, False)):
        original_record = record

        @wraps(original_record)
        def record_v163(kind: str, detail: str = "") -> None:
            if str(kind) == "nonce_drift" and _transient_nonce_maturity(detail):
                LOGGER.warning(
                    "NONCE_V163_MATURITY_DEFERRAL_NOT_COUNTED marker=%s "
                    "activation_still_fail_closed=true circuit_breaker_bypass=false detail=%s",
                    MARKER,
                    detail,
                )
                return
            original_record(kind, detail)

        setattr(record_v163, _PATCH_ATTR, True)
        setattr(record_v163, "__wrapped__", original_record)
        tsm._record_execution_anomaly = record_v163

    if not bool(getattr(gate, _PATCH_ATTR, False)):
        original_gate = gate

        @wraps(original_gate)
        def gate_v163() -> tuple[bool, str]:
            ok, err = original_gate()
            if ok:
                _clear_historical_maturity_breaker(tsm)
            return bool(ok), str(err or "")

        setattr(gate_v163, _PATCH_ATTR, True)
        setattr(gate_v163, "__wrapped__", original_gate)
        tsm._nonce_writer_lease_gate = gate_v163
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_activation_convergence_v163"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        position_ok = _patch_position_sync()
        nonce_ok = _patch_nonce_convergence()
        manifest_ok = _patch_release_manifest()
        ready = bool(position_ok and nonce_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_ACTIVATION_CONVERGENCE_V163_FAILED marker=%s position_ok=%s nonce_ok=%s "
                "manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(position_ok).lower(),
                str(nonce_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_ACTIVATION_CONVERGENCE_V163 marker=%s ready=true "
            "position_adopted_and_fetch_proof=true nonce_maturity_wait_cap_s=5.0 "
            "transient_maturity_not_counted_as_nonce_drift=true historical_maturity_breaker_self_heal=true "
            "stability_requirement_preserved=true safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_connected_platform_brokers_requiring_proof",
    "_position_worker_v163",
    "_transient_nonce_maturity",
    "_clear_historical_maturity_breaker",
]
