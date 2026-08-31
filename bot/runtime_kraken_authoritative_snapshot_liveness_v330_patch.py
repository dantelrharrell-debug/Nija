"""Kraken authoritative Balance/snapshot liveness hardening v330.

Production generation 5075 showed the PLATFORM Kraken v286 authoritative
``Balance`` flight remaining pending across repeated bounded startup callers.
The existing v312 timeout handoff is deliberately strict, but it compares a
fresh authenticated Balance observation with each *retry caller's* start time.
When callers are reusing one older v286 flight, that can reject a genuine
same-credential Balance observed after the underlying authoritative flight
started but just before the newest 5-second retry began.

v330 repairs that epoch mismatch without weakening provenance:

* after the existing v312 timeout path has failed closed, v330 may reuse only a
  structurally valid, credential-proven v312 Balance observation whose timestamp
  is no earlier than the actual still-pending v286 authoritative flight start;
* the old v286 worker is never cancelled, removed, force-released, or marked
  complete by v330, so no duplicate Kraken private read can be created by this
  recovery path;
* v285's existing platform-candidate discovery is widened only for a connected
  Kraken PLATFORM broker whose authoritative snapshot is still current but has
  reached v285's existing proactive refresh interval.  The existing v108/v285
  reconciliation single-flight remains the only worker that performs refresh;
* position snapshot TTL, Kraken rate intervals, transport timeouts, credential
  locks, nonce ordering, capital truth, execution proof, writer/risk/kill-switch,
  order/fill and protective-exit gates are unchanged.

No Balance response, position, freshness, readiness, fill, execution proof, or
activation state is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_authoritative_snapshot_liveness_v330")
MARKER = "20260831-kraken-authoritative-snapshot-liveness-v330"
RELEASE_ID = "20260831-runtime-convergence-v330"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_AUTHORITATIVE_SNAPSHOT_LIVENESS_V330_READY"
_TIMEOUT_PATCH_ATTR = "_nija_kraken_same_flight_epoch_recovery_v330"
_REFRESH_PATCH_ATTR = "_nija_kraken_proactive_snapshot_refresh_v330"
_LOCK = threading.RLock()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _v312() -> Any:
    return importlib.import_module("bot.runtime_kraken_balance_epoch_handoff_v312_patch")


def _v285() -> Any:
    return importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")


def _chain_has_attr(callable_obj: Any, attr: str) -> bool:
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


def _flight_started_at(broker: Any, fallback: float) -> float:
    """Return the actual v286 flight epoch without mutating the flight."""
    try:
        v286 = _v286()
        flights = getattr(v286, "_AUTH_FLIGHTS", None)
        lock = getattr(v286, "_AUTH_LOCK", None)
        if not isinstance(flights, dict):
            return fallback

        def read_started() -> float:
            flight = flights.get(id(broker))
            if not isinstance(flight, dict):
                return fallback
            started = _float(flight.get("started_at"), fallback)
            return started if started > 0.0 else fallback

        if lock is not None and callable(getattr(lock, "__enter__", None)):
            with lock:
                return read_started()
        return read_started()
    except Exception:
        return fallback


def _patch_timeout_epoch_recovery() -> bool:
    """Recover only from a genuine observation newer than the reused v286 flight."""
    v286 = _v286()
    current = getattr(v286, "_authoritative_positions", None)
    if not callable(current):
        return False
    if _chain_has_attr(current, _TIMEOUT_PATCH_ATTR):
        return True
    original = current

    @wraps(original)
    def authoritative_positions_v330(broker: Any):
        retry_started = time.monotonic()
        try:
            return original(broker)
        except TimeoutError as timeout_exc:
            flight_started = _flight_started_at(broker, retry_started)
            try:
                v312 = _v312()
                getter = getattr(v312, "_fresh_observation", None)
                rows_builder = getattr(v312, "_rows_from_observation", None)
                if not callable(getter) or not callable(rows_builder):
                    raise timeout_exc
                observation = getter(broker, not_before=flight_started)
                if not isinstance(observation, dict):
                    raise timeout_exc
                rows = rows_builder(broker, observation)
                LOGGER.critical(
                    "KRAKEN_AUTHORITATIVE_V330_SAME_FLIGHT_HANDOFF marker=%s account=%s held_assets=%d "
                    "flight_age_s=%.3f retry_age_s=%.3f observation_age_s=%.3f "
                    "authenticated_balance=true same_credential=true credential_proven=true "
                    "same_authoritative_flight_epoch=true old_worker_cancelled=false "
                    "old_flight_removed=false duplicate_private_call=false lock_force_release=false "
                    "snapshot_ttl_unchanged=true rate_interval_unchanged=true transport_timeout_unchanged=true "
                    "position_success_fabricated=false readiness_granted=false execution_proof_fabricated=false "
                    "forced_trade=false forced_activation=false safety_gates_bypassed=false",
                    MARKER,
                    str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                    len(rows),
                    max(0.0, time.monotonic() - flight_started),
                    max(0.0, time.monotonic() - retry_started),
                    _float(observation.get("age_s")),
                )
                return [dict(row) for row in rows]
            except TimeoutError:
                raise
            except Exception as exc:
                LOGGER.warning(
                    "KRAKEN_AUTHORITATIVE_V330_HANDOFF_DEFERRED marker=%s account=%s "
                    "error=%s:%s original_timeout_preserved=true fail_closed=true "
                    "duplicate_private_call=false readiness_granted=false safety_gates_bypassed=false",
                    MARKER,
                    str(getattr(broker, "account_identifier", "unknown") or "unknown"),
                    type(exc).__name__,
                    exc,
                )
                raise timeout_exc from exc

    setattr(authoritative_positions_v330, _TIMEOUT_PATCH_ATTR, True)
    setattr(authoritative_positions_v330, "__wrapped__", original)
    v286._authoritative_positions = authoritative_positions_v330
    return True


def _patch_proactive_kraken_refresh() -> bool:
    """Ask v285 to refresh Kraken before its unchanged snapshot TTL expires."""
    v285 = _v285()
    current = getattr(v285, "_platform_candidates", None)
    snapshot_status = getattr(v285, "_snapshot_status", None)
    refresh_interval = getattr(v285, "_refresh_interval_s", None)
    connected = getattr(v285, "_connected", None)
    label = getattr(v285, "_label", None)
    if not callable(current) or not callable(snapshot_status) or not callable(refresh_interval):
        return False
    if _chain_has_attr(current, _REFRESH_PATCH_ATTR):
        return True
    original = current

    @wraps(original)
    def platform_candidates_v330(manager: Any) -> list[tuple[str, Any]]:
        found = list(original(manager) or [])
        seen = {id(broker) for _name, broker in found if broker is not None}
        try:
            refresh_after_s = max(1.0, float(refresh_interval()))
            platform = getattr(manager, "platform_brokers", {}) or {}
            if callable(platform):
                platform = platform()
            platform_items = tuple(dict(platform or {}).items())
        except Exception:
            return found

        for broker_type, broker in platform_items:
            if broker is None or id(broker) in seen:
                continue
            try:
                broker_name = _label(label(broker_type) if callable(label) else broker_type)
            except Exception:
                broker_name = _label(broker_type)
            if broker_name != "kraken":
                continue
            try:
                is_connected = (
                    bool(connected(broker))
                    if callable(connected)
                    else bool(getattr(broker, "connected", False))
                )
            except Exception:
                is_connected = False
            if not is_connected:
                continue
            try:
                snapshot_ok, _reason, _rows, age_s, _generation = snapshot_status(broker)
                age_s = float(age_s)
            except Exception:
                continue
            if not snapshot_ok or age_s < refresh_after_s:
                continue
            found.append(("kraken", broker))
            seen.add(id(broker))
        return found

    setattr(platform_candidates_v330, _REFRESH_PATCH_ATTR, True)
    setattr(platform_candidates_v330, "__wrapped__", original)
    v285._platform_candidates = platform_candidates_v330
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_authoritative_snapshot_liveness_v330"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, bool]:
    timeout_recovery = _patch_timeout_epoch_recovery()
    proactive_refresh = _patch_proactive_kraken_refresh()
    return {
        "timeout_recovery": bool(timeout_recovery),
        "proactive_refresh": bool(proactive_refresh),
        "ready": bool(timeout_recovery and proactive_refresh),
    }


def install() -> bool:
    with _LOCK:
        try:
            state = reconcile_once()
            manifest = _register_manifest()
            ready = bool(state.get("ready") and manifest)
        except Exception as exc:
            state = {"ready": False}
            ready = False
            LOGGER.critical(
                "KRAKEN_AUTHORITATIVE_SNAPSHOT_LIVENESS_V330_NOT_READY marker=%s error=%s:%s "
                "trading_fail_closed=true forced_activation=false safety_gates_bypassed=false",
                MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "KRAKEN_AUTHORITATIVE_SNAPSHOT_LIVENESS_V330_READY marker=%s ready=true "
                "same_flight_epoch_timeout_recovery=true authenticated_balance_only=true "
                "same_credential_only=true old_worker_cancelled=false old_flight_removed=false "
                "duplicate_private_call=false proactive_kraken_refresh=true "
                "v285_refresh_interval_reused=true snapshot_ttl_unchanged=true "
                "rate_interval_unchanged=true transport_timeout_unchanged=true nonce_ordering_unchanged=true "
                "position_readiness_fabricated=false execution_proof_fabricated=false "
                "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true "
                "forced_activation=false safety_gates_bypassed=false",
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
    "reconcile_once",
    "_flight_started_at",
    "_patch_timeout_epoch_recovery",
    "_patch_proactive_kraken_refresh",
]
