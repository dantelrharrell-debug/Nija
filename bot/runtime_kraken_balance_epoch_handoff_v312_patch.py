"""Credential-scoped authenticated Kraken Balance epoch handoff v312.

Production evidence on 2026-08-31 showed a specific liveness race: an old
v286 authoritative PLATFORM Balance flight could remain pending while a newer
capital-refresh Balance call for the exact same Kraken credential completed
successfully.  Position reconciliation then continued waiting on the older
worker even though NIJA already possessed a newer genuine authenticated response
from the same exchange account.

v312 allows the authoritative position flight to consume that newer response,
but only under strict provenance constraints:

* the Balance call completed successfully through the existing v299
  credential-scoped read path;
* v293 proved the credential scope; object-local/unproven identities are never
  shared;
* the observation is no older than a short bounded cache TTL (10 seconds by
  default, hard-capped below the existing position snapshot TTL);
* the observation belongs to the same reconciliation epoch: it was observed no
  earlier than one second before the authoritative flight started;
* the Kraken payload is structurally valid (empty error list and Mapping result).

The handoff only eliminates a redundant same-credential read.  It does not alter
Kraken rate intervals, transport timeouts, nonce ordering, credential locking,
position freshness, capital readiness, writer/risk/kill-switch/order/fill gates,
or execution proof.  It never fabricates a Balance response, position, cost
basis, readiness state, fill, heartbeat marker, or LIVE_ACTIVE transition.
"""
from __future__ import annotations

import copy
import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_kraken_balance_epoch_handoff_v312")
MARKER = "20260831-kraken-balance-epoch-handoff-v312"
RELEASE_ID = "20260831-runtime-convergence-v312"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY"
_V299_PATCH_ATTR = "_nija_kraken_balance_epoch_observer_v312"
_V286_PATCH_ATTR = "_nija_kraken_balance_epoch_handoff_v312"
_LOCK = threading.RLock()
_OBSERVATIONS: dict[str, dict[str, Any]] = {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _ttl_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_BALANCE_EPOCH_HANDOFF_TTL_S", "10") or 10.0)
    except (TypeError, ValueError):
        value = 10.0
    return max(1.0, min(30.0, value))


def _epoch_slack_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_BALANCE_EPOCH_HANDOFF_SLACK_S", "1") or 1.0)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(2.0, value))


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _v299() -> Any:
    return importlib.import_module("bot.runtime_kraken_credential_read_convergence_v299_patch")


def _clone(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _credential_key(broker: Any) -> tuple[str, bool]:
    try:
        helper = getattr(_v299(), "_coordination_key", None)
        if callable(helper):
            key, proven = helper(broker)
            return str(key or ""), bool(proven)
    except Exception:
        pass
    return "", False


def _valid_balance_response(response: Any) -> bool:
    if not isinstance(response, Mapping):
        return False
    errors = response.get("error")
    if errors:
        return False
    return isinstance(response.get("result"), Mapping)


def _record_observation(broker: Any, response: Any) -> bool:
    if not _valid_balance_response(response):
        return False
    key, proven = _credential_key(broker)
    if not key or not proven:
        return False
    now = time.monotonic()
    with _LOCK:
        _OBSERVATIONS[key] = {
            "response": _clone(response),
            "observed_at": now,
            "account": str(getattr(broker, "account_identifier", "unknown") or "unknown"),
        }
        # Bound process-local diagnostic/provenance state.  This normally holds
        # only a handful of credentials, but never allow unbounded growth.
        if len(_OBSERVATIONS) > 64:
            oldest = sorted(
                _OBSERVATIONS.items(),
                key=lambda item: _float(item[1].get("observed_at")),
            )[: len(_OBSERVATIONS) - 64]
            for stale_key, _row in oldest:
                _OBSERVATIONS.pop(stale_key, None)
    return True


def _fresh_observation(broker: Any, *, not_before: float) -> dict[str, Any] | None:
    key, proven = _credential_key(broker)
    if not key or not proven:
        return None
    now = time.monotonic()
    with _LOCK:
        row = _OBSERVATIONS.get(key)
        if not isinstance(row, dict):
            return None
        observed_at = _float(row.get("observed_at"))
        age = max(0.0, now - observed_at)
        if age > _ttl_s():
            _OBSERVATIONS.pop(key, None)
            return None
        if observed_at + _epoch_slack_s() < max(0.0, float(not_before or 0.0)):
            return None
        response = row.get("response")
        if not _valid_balance_response(response):
            return None
        return {
            "response": _clone(response),
            "observed_at": observed_at,
            "age_s": age,
            "account": str(row.get("account") or "unknown"),
        }


def _patch_v299_observer() -> bool:
    v299 = _v299()
    current = getattr(v299, "_credential_balance_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _V299_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def credential_balance_v312(broker: Any, call: Callable[[], Any]) -> Any:
        response = original(broker, call)
        if _record_observation(broker, response):
            LOGGER.debug(
                "KRAKEN_BALANCE_EPOCH_V312_OBSERVED marker=%s account=%s "
                "credential_proven=true authenticated_balance=true response_valid=true "
                "freshness_extended=false readiness_granted=false",
                MARKER,
                str(getattr(broker, "account_identifier", "unknown") or "unknown"),
            )
        return response

    setattr(credential_balance_v312, _V299_PATCH_ATTR, True)
    setattr(credential_balance_v312, "__wrapped__", original)
    v299._credential_balance_call = credential_balance_v312
    return True


def _patch_v286_finish_flight() -> bool:
    v286 = _v286()
    current = getattr(v286, "_finish_auth_flight", None)
    if not callable(current):
        return False
    if bool(getattr(current, _V286_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def finish_auth_flight_v312(flight: dict[str, Any], broker: Any) -> None:
        started_at = _float(flight.get("started_at")) if isinstance(flight, dict) else 0.0
        observation = _fresh_observation(broker, not_before=started_at)
        if observation is None:
            return original(flight, broker)

        try:
            response = observation["response"]
            result = response.get("result")
            if not isinstance(result, Mapping):
                return original(flight, broker)
            builder = getattr(v286, "_build_authoritative_rows", None)
            recorder = getattr(v286, "_record_snapshot_success", None)
            if not callable(builder) or not callable(recorder):
                return original(flight, broker)
            rows = builder(broker, result)
            recorder(broker, rows)
            flight["result"] = [dict(row) for row in rows]
            flight["error"] = None
            flight["finished_at"] = time.monotonic()
            event = flight.get("event")
            if callable(getattr(event, "set", None)):
                event.set()
            LOGGER.critical(
                "KRAKEN_BALANCE_EPOCH_V312_HANDOFF marker=%s account=%s held_assets=%d "
                "observation_age_s=%.3f same_credential=true credential_proven=true "
                "authenticated_balance=true newer_reconciliation_epoch=true redundant_read_eliminated=true "
                "rate_interval_unchanged=true transport_timeout_unchanged=true snapshot_ttl_unchanged=true "
                "position_success_fabricated=false readiness_granted=false execution_proof_fabricated=false "
                "forced_trade=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                len(rows),
                float(observation.get("age_s", 0.0) or 0.0),
            )
            return None
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_BALANCE_EPOCH_V312_HANDOFF_DEFERRED marker=%s account=%s error=%s:%s "
                "fallback=normal_authoritative_read fail_closed=true readiness_granted=false",
                MARKER,
                str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                type(exc).__name__,
                exc,
            )
            return original(flight, broker)

    setattr(finish_auth_flight_v312, _V286_PATCH_ATTR, True)
    setattr(finish_auth_flight_v312, "__wrapped__", original)
    v286._finish_auth_flight = finish_auth_flight_v312
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_balance_epoch_handoff_v312"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    observer = _patch_v299_observer()
    handoff = _patch_v286_finish_flight()
    with _LOCK:
        observations = len(_OBSERVATIONS)
    return {
        "ready": bool(observer and handoff),
        "v299_observer": bool(observer),
        "v286_handoff": bool(handoff),
        "observations": int(observations),
    }


def install() -> bool:
    try:
        manifest = _register_manifest()
        state = reconcile_once()
    except Exception as exc:
        manifest = False
        state = {"ready": False, "error": f"{type(exc).__name__}:{exc}"}
    ready = bool(manifest and state.get("ready"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_%s marker=%s ready=%s "
        "authenticated_balance_only=true same_credential_only=true credential_proof_required=true "
        "epoch_bounded=true cache_ttl_s=%.1f snapshot_ttl_unchanged=true rate_interval_unchanged=true "
        "transport_timeout_unchanged=true nonce_ordering_unchanged=true lock_bypass=false lock_force_release=false "
        "position_success_fabricated=false readiness_granted=false execution_proof_fabricated=false "
        "forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        _ttl_s(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_ttl_s",
    "_credential_key",
    "_valid_balance_response",
    "_record_observation",
    "_fresh_observation",
    "_patch_v299_observer",
    "_patch_v286_finish_flight",
]
