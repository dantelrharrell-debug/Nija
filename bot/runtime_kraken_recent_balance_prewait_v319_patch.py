"""Pre-activation Kraken recent-Balance prewait reuse v319.

Generation 5052 proved the v318 ordering repair: PLATFORM authoritative reads now
enter the priority gate immediately, but Kraken's legitimate monitoring rate
interval can still require ~58 seconds of prewait while the authoritative
position caller remains bounded to 5 seconds. Shortening that exchange pacing or
extending startup until a full additional interval would weaken liveness/safety.

v319 instead reuses a genuine authenticated same-credential ``Balance`` response
already observed by v312 when all of the following are true:

* canonical runtime has not reached LIVE_ACTIVE;
* v312 has a structurally valid, credential-proven Balance observation;
* that observation is still inside v312's existing short cache TTL (10 seconds
  by default, hard-capped at 30 seconds and well below v285's 90-second position
  snapshot TTL);
* a new v286 authoritative flight is about to issue a redundant Balance call.

Only the new-flight pre-read path is changed. Existing-flight timeout recovery
keeps v312's stricter same-epoch rule. The authenticated payload is converted by
v312's existing authoritative row builder and recorded through v285. No rate
interval, transport timeout, nonce ordering, lock semantics, snapshot TTL,
position quantity, cost basis, execution proof, order, fill, or activation gate
is relaxed or fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_recent_balance_prewait_v319")
MARKER = "20260831-kraken-recent-balance-prewait-v319"
RELEASE_ID = "20260831-runtime-convergence-v319"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_RECENT_BALANCE_PREWAIT_V319_READY"
_PATCH_ATTR = "_nija_kraken_recent_balance_prewait_v319"


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _v312() -> Any:
    return importlib.import_module("bot.runtime_kraken_balance_epoch_handoff_v312_patch")


def _preactivation() -> bool:
    state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
    return state != "LIVE_ACTIVE"


def _chain_has_patch(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PATCH_ATTR, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _recent_observation(broker: Any) -> dict[str, Any] | None:
    v312 = _v312()
    getter = getattr(v312, "_fresh_observation", None)
    if not callable(getter):
        return None
    # not_before=0 intentionally changes only v312's same-attempt requirement on
    # this pre-read path. _fresh_observation still enforces same credential,
    # structural validity, and the existing v312 short TTL.
    row = getter(broker, not_before=0.0)
    return dict(row) if isinstance(row, dict) else None


def _patch_v286_new_flight() -> bool:
    v286 = _v286()
    current = getattr(v286, "_finish_auth_flight", None)
    if not callable(current):
        return False
    if _chain_has_patch(current):
        return True
    original = current

    @wraps(original)
    def finish_auth_flight_v319(flight: dict[str, Any], broker: Any) -> None:
        if not _preactivation():
            return original(flight, broker)

        observation = _recent_observation(broker)
        if observation is None:
            return original(flight, broker)

        try:
            started_at = float(flight.get("started_at", 0.0) or 0.0)
            observed_at = float(observation.get("observed_at", 0.0) or 0.0)
            age_s = float(observation.get("age_s", 0.0) or 0.0)
            pre_attempt_age_s = max(0.0, started_at - observed_at)
            v312 = _v312()
            rows_builder = getattr(v312, "_rows_from_observation", None)
            if not callable(rows_builder):
                raise RuntimeError("v312_rows_from_observation_unavailable")
            rows = rows_builder(broker, observation)
            flight["result"] = [dict(row) for row in rows]
            flight["error"] = None
            flight["finished_at"] = time.monotonic()
            event = flight.get("event")
            if callable(getattr(event, "set", None)):
                event.set()
            LOGGER.critical(
                "KRAKEN_RECENT_BALANCE_PREWAIT_V319_REUSED marker=%s account=%s held_assets=%d "
                "observation_age_s=%.3f pre_attempt_age_s=%.3f authenticated_balance=true "
                "same_credential=true credential_proven=true preactivation_only=true "
                "v312_cache_ttl_unchanged=true position_snapshot_ttl_unchanged=true "
                "redundant_rate_prewait_eliminated=true configured_rate_interval_unchanged=true "
                "transport_timeout_unchanged=true nonce_ordering_unchanged=true "
                "old_worker_cancelled=false lock_bypass=false lock_force_release=false "
                "position_success_fabricated=false balance_fabricated=false readiness_granted=false "
                "execution_proof_fabricated=false forced_trade=false forced_activation=false "
                "safety_gates_bypassed=false",
                MARKER,
                str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                len(rows),
                age_s,
                pre_attempt_age_s,
            )
            return None
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_RECENT_BALANCE_PREWAIT_V319_DEFERRED marker=%s account=%s error=%s:%s "
                "fallback=v312_normal_path fail_closed=true rate_interval_unchanged=true "
                "readiness_granted=false execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                type(exc).__name__,
                exc,
            )
            return original(flight, broker)

    setattr(finish_auth_flight_v319, _PATCH_ATTR, True)
    setattr(finish_auth_flight_v319, "__wrapped__", original)
    v286._finish_auth_flight = finish_auth_flight_v319
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_recent_balance_prewait_v319"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    try:
        v312_ready = os.environ.get("NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY") == "1"
        if not v312_ready:
            raise RuntimeError("v312_not_ready")
        patched = _patch_v286_new_flight()
        manifest = _register_manifest()
        ready = bool(patched and manifest)
    except Exception as exc:
        ready = False
        LOGGER.critical(
            "KRAKEN_RECENT_BALANCE_PREWAIT_V319_NOT_READY marker=%s error=%s:%s "
            "trading_fail_closed=true rate_interval_unchanged=true safety_gates_bypassed=false",
            MARKER,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "KRAKEN_RECENT_BALANCE_PREWAIT_V319_READY marker=%s ready=true "
            "preactivation_only=true authenticated_balance_only=true same_credential_only=true "
            "v312_cache_ttl_unchanged=true position_snapshot_ttl_unchanged=true "
            "same_epoch_timeout_recovery_unchanged=true configured_rate_interval_unchanged=true "
            "transport_timeout_unchanged=true nonce_ordering_unchanged=true lock_bypass=false "
            "lock_force_release=false position_success_fabricated=false balance_fabricated=false "
            "readiness_granted=false execution_proof_fabricated=false forced_activation=false "
            "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_preactivation",
    "_recent_observation",
    "_patch_v286_new_flight",
]
