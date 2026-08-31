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

Production generation 5056 exposed one remaining provenance gap: a genuine
canonical Kraken ``Balance`` call could complete successfully in the ordinary
account-balance path without passing through v312's narrower v299 observer
surface. The v321 observer extension in this module records that already-issued
successful canonical response through v312's existing credential-proven cache.
It never starts another broker call and never changes the response or exception
semantics. That lets the existing v312/v319 handoff eliminate the otherwise
redundant ~58 second monitoring prewait.

v320 is chained from this already-canonical fast-path installer. It does not
change v319's Kraken behavior; it arms the platform/user position-readiness
isolation hook so v285's strong all-account proof can continue protecting each
user account without letting an unproven user revoke otherwise-valid PLATFORM
activation.

v330 is also chained here after v320. It keeps the same fail-closed contract and
repairs only Kraken authoritative Balance/snapshot liveness: a timed-out retry
may recover from a genuine credential-proven Balance observed during the same
underlying v286 flight epoch, and still-current Kraken platform snapshots are
queued for refresh at v285's existing refresh interval before expiry. v330 does
not cancel workers, create duplicate private reads, extend freshness, or grant
readiness.
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
BALANCE_OBSERVER_MARKER = "20260831-kraken-canonical-balance-observer-v321"
RELEASE_ID = "20260831-runtime-convergence-v319"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_RECENT_BALANCE_PREWAIT_V319_READY"
_PATCH_ATTR = "_nija_kraken_recent_balance_prewait_v319"
_BALANCE_OBSERVER_ATTR = "_nija_kraken_canonical_balance_observer_v321"


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _v312() -> Any:
    return importlib.import_module("bot.runtime_kraken_balance_epoch_handoff_v312_patch")


def _broker_module() -> Any:
    return importlib.import_module("bot.broker_manager")


def _preactivation() -> bool:
    state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
    return state != "LIVE_ACTIVE"


def _chain_has_patch(callable_obj: Any, attr: str = _PATCH_ATTR) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, attr, False)):
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


def _patch_canonical_balance_observer() -> bool:
    """Record already-issued successful canonical Balance reads for v312 reuse.

    This wrapper is observation-only: it delegates exactly once to the existing
    canonical private-call chain, preserves all exceptions and return values, and
    records only a successful ``Balance`` response through v312's existing
    credential-proven validator/cache.
    """
    try:
        cls = getattr(_broker_module(), "KrakenBroker", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if _chain_has_patch(current, _BALANCE_OBSERVER_ATTR):
        return True
    original = current

    @wraps(original)
    def private_balance_observer_v321(self: Any, *args: Any, **kwargs: Any):
        method = str(args[0] if args else kwargs.get("method", "") or "")
        response = original(self, *args, **kwargs)
        if method != "Balance":
            return response

        recorded = False
        try:
            recorder = getattr(_v312(), "_record_observation", None)
            if callable(recorder):
                recorded = bool(recorder(self, response))
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_CANONICAL_BALANCE_OBSERVER_V321_DEFERRED marker=%s account=%s "
                "error=%s:%s response_unchanged=true exception_semantics_unchanged=true "
                "new_broker_io=false readiness_granted=false execution_proof_fabricated=false "
                "safety_gates_bypassed=false",
                BALANCE_OBSERVER_MARKER,
                str(getattr(self, "account_identifier", "unknown") or "unknown"),
                type(exc).__name__,
                exc,
            )
            return response

        if recorded:
            LOGGER.critical(
                "KRAKEN_CANONICAL_BALANCE_OBSERVER_V321_RECORDED marker=%s account=%s "
                "authenticated_balance=true credential_proven=true same_credential_cache=true "
                "v312_cache_ttl_unchanged=true response_unchanged=true exception_semantics_unchanged=true "
                "new_broker_io=false rate_interval_unchanged=true transport_timeout_unchanged=true "
                "nonce_ordering_unchanged=true lock_bypass=false lock_force_release=false "
                "position_success_fabricated=false balance_fabricated=false readiness_granted=false "
                "execution_proof_fabricated=false forced_trade=false forced_activation=false "
                "safety_gates_bypassed=false",
                BALANCE_OBSERVER_MARKER,
                str(getattr(self, "account_identifier", "unknown") or "unknown"),
            )
        return response

    setattr(private_balance_observer_v321, _BALANCE_OBSERVER_ATTR, True)
    setattr(private_balance_observer_v321, "__wrapped__", original)
    cls._kraken_private_call = private_balance_observer_v321
    return True


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


def _install_platform_position_isolation_v320() -> bool:
    try:
        module = importlib.import_module("bot.runtime_platform_position_sync_isolation_v320_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if not callable(installer):
            return False
        return bool(installer())
    except Exception as exc:
        LOGGER.critical(
            "KRAKEN_RECENT_BALANCE_PREWAIT_V319_V320_CHAIN_FAILED marker=%s error=%s:%s "
            "trading_fail_closed=true forced_activation=false safety_gates_bypassed=false",
            MARKER,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False


def _install_kraken_authoritative_snapshot_liveness_v330() -> bool:
    try:
        module = importlib.import_module("bot.runtime_kraken_authoritative_snapshot_liveness_v330_patch")
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if not callable(installer):
            return False
        return bool(installer())
    except Exception as exc:
        LOGGER.critical(
            "KRAKEN_RECENT_BALANCE_PREWAIT_V319_V330_CHAIN_FAILED marker=%s error=%s:%s "
            "trading_fail_closed=true duplicate_private_call=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False


def install() -> bool:
    try:
        v312_ready = os.environ.get("NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY") == "1"
        if not v312_ready:
            raise RuntimeError("v312_not_ready")
        observer = _patch_canonical_balance_observer()
        patched = _patch_v286_new_flight()
        manifest = _register_manifest()
        v320 = _install_platform_position_isolation_v320()
        v330 = _install_kraken_authoritative_snapshot_liveness_v330()
        ready = bool(observer and patched and manifest and v320 and v330)
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
            "canonical_balance_observer_v321=true platform_position_isolation_v320=true "
            "kraken_authoritative_snapshot_liveness_v330=true "
            "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "BALANCE_OBSERVER_MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_preactivation",
    "_recent_observation",
    "_patch_canonical_balance_observer",
    "_patch_v286_new_flight",
    "_install_platform_position_isolation_v320",
    "_install_kraken_authoritative_snapshot_liveness_v330",
]
