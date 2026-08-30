"""Preserve current Kraken position proof during bounded in-flight waits (v298).

Production on 2026-08-30 exposed a classification bug after v297 restored fair
Kraken Balance scheduling.  v286 intentionally gives callers only a short local
wait slice while one genuine authenticated Balance single-flight may remain in
progress for the exchange's preserved monitoring interval.  v98 correctly
revokes a previously proven position snapshot after a *completed* fetch failure,
but the v286 local ``Balance pending after 5.0s`` exception is not a completed
broker failure: the same authoritative flight is still running.

That local timeout flowed through v98 and v286 and cleared both startup adoption
proof and v285 snapshot-fetch proof even when the existing authenticated snapshot
was still inside its unchanged 90-second freshness policy.  Production therefore
oscillated from all-platform position readiness to fail-closed roughly twenty
seconds after a genuine Kraken reconciliation.

v298 makes only that distinction.  When, and only when:

* the broker had a complete strong Kraken position proof before the refresh;
* the existing v285 snapshot is still within the original freshness limit;
* the exception is exactly v286's bounded local ``authoritative ... pending``
  wait; and
* the same v286 authoritative flight is demonstrably still in progress,

v298 restores the pre-call proof fields and treats the refresh as still in
flight.  It does not advance the snapshot timestamp or generation, publish a new
position, extend freshness, turn an error into success, or suppress a completed
exchange/transport/shared-flight failure.  Once the genuine snapshot ages past
the existing limit, fail-closed behavior is unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_inflight_snapshot_truth_v298")
MARKER = "20260830-kraken-inflight-snapshot-truth-v298"
RELEASE_ID = "20260830-runtime-convergence-v298"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_INFLIGHT_SNAPSHOT_TRUTH_V298_READY"
_PATCH_ATTR = "_nija_kraken_inflight_snapshot_truth_v298"
_LOCK = threading.RLock()

_PROOF_ATTRS = (
    "_startup_position_sync_adopted",
    "_startup_position_sync_symbols",
    "_startup_position_sync_fetch_ok",
    "_startup_position_sync_error",
    "_nija_authoritative_position_snapshot_fetch_ok_v285",
    "_nija_authoritative_position_snapshot_error_v285",
)
_LOCAL_PENDING_TEXT = "Kraken authoritative position Balance pending after"


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _real_broker(broker: Any) -> Any:
    return getattr(broker, "_broker", broker)


def _is_kraken_broker(broker: Any) -> bool:
    broker = _real_broker(broker)
    if broker is None:
        return False
    if _label(getattr(broker, "broker_type", "")) == "kraken":
        return True
    return type(broker).__name__.lower() == "krakenbroker"


def _v285() -> Any:
    return importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _strong_proof(broker: Any) -> tuple[bool, str]:
    try:
        probe = getattr(_v285(), "_strong_broker_proof", None)
        if callable(probe):
            ready, reason = probe(broker)
            return bool(ready), str(reason or "")
    except Exception as exc:
        return False, f"v285_strong_proof_error:{type(exc).__name__}:{exc}"
    return False, "v285_strong_proof_unavailable"


def _snapshot_age_s(broker: Any) -> tuple[float, float]:
    try:
        recorded = float(
            getattr(broker, "_nija_authoritative_position_snapshot_at_v285", 0.0) or 0.0
        )
    except Exception:
        recorded = 0.0
    try:
        maximum = float(getattr(_v285(), "_snapshot_max_age_s")())
    except Exception:
        maximum = 90.0
    age = max(0.0, time.monotonic() - recorded) if recorded > 0.0 else float("inf")
    return age, max(1.0, maximum)


def _active_authoritative_flight(broker: Any) -> tuple[bool, float]:
    """Return true only while v286's exact broker flight is still unfinished."""
    try:
        module = _v286()
        lock = getattr(module, "_AUTH_LOCK", None)
        flights = getattr(module, "_AUTH_FLIGHTS", None)
        if lock is None or not isinstance(flights, dict):
            return False, 0.0
        with lock:
            flight = flights.get(id(broker))
            if not isinstance(flight, dict):
                return False, 0.0
            event = flight.get("event")
            if event is None or not callable(getattr(event, "is_set", None)):
                return False, 0.0
            if bool(event.is_set()):
                return False, 0.0
            if flight.get("error") is not None:
                return False, 0.0
            started = float(flight.get("started_at", 0.0) or 0.0)
            age = max(0.0, time.monotonic() - started) if started > 0.0 else 0.0
            return True, age
    except Exception:
        return False, 0.0


def _local_pending_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) and _LOCAL_PENDING_TEXT in str(exc)


def _capture_proof_fields(broker: Any) -> dict[str, Any]:
    return {name: getattr(broker, name, None) for name in _PROOF_ATTRS}


def _restore_proof_fields(broker: Any, prior: dict[str, Any]) -> None:
    for name in _PROOF_ATTRS:
        try:
            setattr(broker, name, prior.get(name))
        except Exception:
            pass


def _should_preserve(
    broker: Any,
    exc: BaseException,
    *,
    pre_ready: bool,
) -> tuple[bool, str, float, float, float]:
    if not pre_ready:
        return False, "preexisting_proof_not_ready", 0.0, 0.0, 0.0
    if not _local_pending_timeout(exc):
        return False, "not_local_pending_timeout", 0.0, 0.0, 0.0
    snapshot_age, max_age = _snapshot_age_s(broker)
    if snapshot_age >= max_age:
        return False, "snapshot_not_current", snapshot_age, max_age, 0.0
    active, flight_age = _active_authoritative_flight(broker)
    if not active:
        return False, "authoritative_flight_not_active", snapshot_age, max_age, flight_age
    return True, "current_proof_refresh_still_inflight", snapshot_age, max_age, flight_age


def _patch_startup_adopter() -> bool:
    try:
        sync = importlib.import_module("bot.startup_position_sync")
    except Exception:
        return False
    current = getattr(sync, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def adopt_v298(broker: Any, broker_name: str, eps: Any) -> int:
        real = _real_broker(broker)
        if not _is_kraken_broker(real):
            return int(original(broker, broker_name, eps) or 0)

        pre_ready, pre_reason = _strong_proof(real)
        prior = _capture_proof_fields(real)
        try:
            return int(original(broker, broker_name, eps) or 0)
        except BaseException as exc:
            preserve, reason, snapshot_age, max_age, flight_age = _should_preserve(
                real,
                exc,
                pre_ready=pre_ready,
            )
            if not preserve:
                raise

            # v98/v286 have already classified the caller timeout as a completed
            # failure by this point. Restore exactly the proof that existed before
            # the call; do not mutate rows, timestamp, generation, or global gates.
            _restore_proof_fields(real, prior)
            LOGGER.info(
                "KRAKEN_INFLIGHT_SNAPSHOT_V298_PRESERVED marker=%s account=%s "
                "pre_reason=%s snapshot_age_s=%.3f max_age_s=%.3f flight_age_s=%.3f "
                "local_wait_only=true authoritative_flight_active=true "
                "snapshot_timestamp_unchanged=true snapshot_generation_unchanged=true "
                "freshness_extended=false position_success_fabricated=false "
                "exchange_transport_errors_unchanged=true trading_fail_closed_after_expiry=true "
                "safety_gates_bypassed=false",
                MARKER,
                str(broker_name or getattr(real, "account_identifier", "kraken")),
                pre_reason or "strong_proof_ready",
                snapshot_age,
                max_age,
                flight_age,
            )
            return 0

    adopt_v298.__name__ = "adopt_v298"
    setattr(adopt_v298, _PATCH_ATTR, True)
    setattr(adopt_v298, "__wrapped__", original)
    sync._adopt_broker_positions = adopt_v298
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_inflight_snapshot_truth_v298"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        patched = _patch_startup_adopter()
        manifest = _register_manifest()
        ready = bool(patched and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_INFLIGHT_SNAPSHOT_TRUTH_V298_%s marker=%s ready=%s "
        "local_wait_timeout_classified_as_inflight_only=true preexisting_current_proof_required=true "
        "same_authoritative_flight_required=true snapshot_ttl_unchanged=true "
        "snapshot_timestamp_unchanged=true completed_failures_unchanged=true "
        "exchange_errors_unchanged=true transport_errors_unchanged=true "
        "position_success_fabricated=false forced_activation=false safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_startup_adopter",
    "_should_preserve",
    "_active_authoritative_flight",
    "_local_pending_timeout",
]
