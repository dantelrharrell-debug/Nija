"""Bridge fresh CapitalAuthority broker observations into v162 stale-flight recovery.

Production 2026-09-10 showed Kraken balance reads continuing successfully through
multi-account/CapitalAuthority while the v35 capital worker remained stuck past
its timeout with the orphan cap saturated.  v162 intentionally refuses to rotate
that worker unless it can prove a fresh broker-owned observation, but its proof
path only looked at the v35 observation cache / broker-local timestamp fields.

This patch adds a narrowly-scoped second proof source: the canonical
CapitalAuthority per-broker feed, including its original broker feed timestamp.
It never refreshes timestamps, never creates a balance, never calls the network,
and never grants execution authority.  If the per-broker feed is absent, zero,
or older than the canonical freshness TTL, recovery remains fail-closed.

The same production incident also exposed a separate authoritative Kraken
position single-flight that could remain pending after the capital path had
recovered.  The repository already contains v287, which safely retires only dead
or demonstrably over-age position workers.  v391 now ensures that existing v287
recovery monitor is installed whenever this bridge is installed.  No timeout is
shortened and no position success is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_stale_flight_authority_bridge_v391")
MARKER = "20260910-kraken-stale-flight-authority-bridge-v391"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_STALE_FLIGHT_AUTHORITY_BRIDGE_V391_READY"
_PATCH_ATTR = "_nija_kraken_stale_flight_authority_bridge_v391"
_LOCK = threading.RLock()


def _epoch(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            result = value.timestamp()
        elif hasattr(value, "timestamp") and callable(value.timestamp):
            result = float(value.timestamp())
        else:
            result = float(value)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return result if math.isfinite(result) and result > 0.0 else None


def _authority_observation(guard: Any, broker_id: str) -> bool:
    bid = str(broker_id).strip().lower()
    try:
        capital = importlib.import_module("bot.capital_authority")
        getter = getattr(capital, "get_capital_authority", None)
        authority = getter() if callable(getter) else None
    except Exception:
        return False
    if authority is None:
        return False

    try:
        ttl_getter = getattr(guard, "_freshness_ttl_seconds", None)
        ttl_s = float(ttl_getter()) if callable(ttl_getter) else 90.0
    except (TypeError, ValueError):
        ttl_s = 90.0
    ttl_s = max(1.0, ttl_s)

    auth_lock = getattr(authority, "_lock", None)

    def read_authority() -> tuple[Any, Any]:
        balances = getattr(authority, "_broker_balances", {}) or {}
        timestamps = getattr(authority, "_broker_feed_timestamps", {}) or {}
        if not isinstance(balances, dict) or not isinstance(timestamps, dict):
            return None, None
        return balances.get(bid), timestamps.get(bid)

    if auth_lock is None:
        raw_value, raw_timestamp = read_authority()
    else:
        try:
            with auth_lock:
                raw_value, raw_timestamp = read_authority()
        except Exception:
            return False

    scalar_fn = getattr(guard, "_coerce_scalar", None)
    if not callable(scalar_fn):
        return False
    try:
        value = scalar_fn(raw_value)
        observed_epoch = _epoch(raw_timestamp)
    except Exception:
        return False
    if value is None or float(value) <= 0.0 or observed_epoch is None:
        return False

    age_s = max(0.0, time.time() - observed_epoch)
    if age_s > ttl_s:
        return False

    observations = getattr(guard, "_OBSERVATIONS", None)
    observation_cls = getattr(guard, "_Observation", None)
    observation_lock = getattr(guard, "_OBSERVATION_LOCK", None)
    sequence_map = getattr(guard, "_BROKER_SEQUENCE", {})
    if not isinstance(observations, dict) or observation_cls is None:
        return False

    sequence = int(sequence_map.get(bid, 0) or 0) if isinstance(sequence_map, dict) else 0
    observed_mono = max(0.0, time.monotonic() - age_s)
    try:
        observation = observation_cls(
            value=float(value),
            observed_monotonic=observed_mono,
            observed_epoch=observed_epoch,
            sequence=sequence,
        )
    except TypeError:
        observation = observation_cls(float(value), observed_mono, observed_epoch, sequence)

    def store() -> bool:
        previous = observations.get(bid)
        previous_mono = float(getattr(previous, "observed_monotonic", 0.0) or 0.0)
        if previous is None or observed_mono >= previous_mono:
            observations[bid] = observation
            return True
        return False

    if observation_lock is None:
        stored = store()
    else:
        try:
            with observation_lock:
                stored = store()
        except Exception:
            return False

    if stored:
        LOGGER.critical(
            "KRAKEN_STALE_FLIGHT_AUTHORITY_PROOF_V391 marker=%s broker=%s balance=%.8f age_s=%.2f ttl_s=%.2f "
            "source=capital_authority_broker_feed timestamp_preserved=true freshness_extended=false "
            "network_call=false execution_authority_granted=false",
            MARKER,
            bid,
            float(value),
            age_s,
            ttl_s,
        )
    return stored


def _install_position_flight_recovery() -> bool:
    """Ensure the existing bounded v287 position-flight recovery is active."""
    try:
        v287 = importlib.import_module("bot.runtime_kraken_position_flight_recovery_v287_patch")
        installer = getattr(v287, "install", None) or getattr(v287, "install_import_hook", None)
        ready = bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.error(
            "KRAKEN_POSITION_FLIGHT_RECOVERY_V391_INSTALL_FAILED marker=%s error=%s:%s "
            "position_sync_remains_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    if not ready:
        LOGGER.error(
            "KRAKEN_POSITION_FLIGHT_RECOVERY_V391_NOT_READY marker=%s position_sync_remains_fail_closed=true",
            MARKER,
        )
        return False
    LOGGER.critical(
        "KRAKEN_POSITION_FLIGHT_RECOVERY_V391_READY marker=%s v287_ready=true timeout_shortened=false "
        "position_success_fabricated=false snapshot_freshness_unchanged=true execution_authority_granted=false "
        "safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install() -> bool:
    with _LOCK:
        try:
            v162 = importlib.import_module("bot.runtime_capital_late_observation_fence_v162_patch")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.error("KRAKEN_STALE_FLIGHT_AUTHORITY_BRIDGE_V391_IMPORT_FAILED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
            return False

        current = getattr(v162, "_fresh_broker_observation", None)
        if not callable(current):
            os.environ[_READY_FLAG] = "0"
            return False

        if not getattr(current, _PATCH_ATTR, False):
            original = current

            @wraps(original)
            def fresh_observation(guard: Any, v161: Any, broker_id: str, broker: Any) -> bool:
                if original(guard, v161, broker_id, broker):
                    return True
                if str(broker_id).strip().lower() != "kraken":
                    return False
                return _authority_observation(guard, broker_id)

            setattr(fresh_observation, _PATCH_ATTR, True)
            setattr(fresh_observation, "__wrapped__", original)
            v162._fresh_broker_observation = fresh_observation

        if not _install_position_flight_recovery():
            os.environ[_READY_FLAG] = "0"
            return False

        os.environ[_READY_FLAG] = "1"
        LOGGER.critical(
            "KRAKEN_STALE_FLIGHT_AUTHORITY_BRIDGE_V391_INSTALLED marker=%s ready=true "
            "capital_authority_feed_timestamp_required=true position_v287_required=true "
            "freshness_extended=false network_call=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_authority_observation",
    "_install_position_flight_recovery",
]
