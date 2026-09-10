"""Fence retired broker-balance observations after v161 flight rotation.

v161 safely rotates a v35 balance flight before it can consume the full capital
publication budget. The underlying daemon cannot be killed safely, however, and
v35 records a successful worker result in its global observation cache before
checking whether that flight is still the process-authoritative in-flight
request. A retired response could therefore become a newly-fresh fallback even
though v142 correctly prevents its retired coordinator generation from
publishing.

v162 closes that narrow race. Before v161 removes a stale flight, this wrapper
advances the broker sequence and carries the last authoritative observation
forward under that new fence. If no prior observation exists, it installs a
zero-value, age-invalid tombstone. The retired worker's lower sequence can no
longer replace the cache; the next live worker receives a still-higher sequence
and can publish a real fresh observation normally.

Production on 2026-09-09 exposed one additional liveness edge: when the strict
orphan cap was already full, the stale current flight was reused forever even
when a separate broker-owned, timestamped balance observation proved that the
credential path had recovered. The stale flight could then remain registered
for hundreds of seconds and starve authoritative capital/position convergence.

The saturation recovery below permits exactly one bounded over-cap retirement
per broker, and only when a fresh broker-owned observation exists. The retired
worker is generation-fenced before removal. No stale value is refreshed and no
new request is created by this module; the existing v35 constructor may start
its normal replacement worker after the stale current flight is removed. If
that replacement also stalls while the over-cap orphan is still alive, the
system returns to fail-closed capped behavior instead of creating unbounded
threads. Capacity becomes eligible for one recovery again only after orphan
count falls back to the configured cap or lower.

No capital value is invented, no stale value is refreshed, and no trading gate
is bypassed.
Production on 2026-09-09 exposed a second liveness edge: when the normal orphan
cap was already full, a third stale Kraken flight was reused forever. This file
now permits one hard-saturation recovery probe per broker. The stuck current
flight is sequence-fenced before removal and retained separately, so its late
result cannot become authoritative. A second escape is forbidden until a newer
authoritative observation proves that the recovery probe completed. This keeps
recovery bounded instead of creating an unbounded thread leak.

No capital value is invented, no stale value is refreshed, no existing orphan
cap is raised, and no trading gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_late_observation_fence_v162")
MARKER = "20260819-runtime-capital-late-observation-fence-v162"
SATURATION_MARKER = "20260909-runtime-capital-stale-flight-saturation-v390"
_PATCH_ATTR = "_nija_runtime_capital_late_observation_fence_v162"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_LATE_OBSERVATION_FENCE_V162_READY"
_LOCK = threading.RLock()
_SATURATION_RECOVERY_USED: set[str] = set()
_SATURATION_ESCAPE: dict[str, dict[str, Any]] = {}


def _v161():
    return importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")


def _hard_saturation_after_seconds(stale_after_s: float) -> float:
    raw = str(os.environ.get("NIJA_CAPITAL_HARD_SATURATION_AFTER_S", "") or "").strip()
    default = max(180.0, float(stale_after_s) * 3.0)
    if raw:
        try:
            requested = float(raw)
        except (TypeError, ValueError):
            requested = default
    else:
        requested = default
    return max(float(stale_after_s) + 10.0, min(requested, 900.0))


def _escape_recovered(guard: Any, broker_id: str) -> bool:
    bid = str(broker_id).strip().lower()
    state = _SATURATION_ESCAPE.get(bid)
    if not isinstance(state, dict):
        return False
    observations = getattr(guard, "_OBSERVATIONS", None)
    if not isinstance(observations, dict):
        return False
    observation = observations.get(bid)
    if observation is None:
        return False
    try:
        observation_sequence = int(getattr(observation, "sequence", 0) or 0)
        fence_sequence = int(state.get("fence_sequence", 0) or 0)
        observed_monotonic = float(getattr(observation, "observed_monotonic", 0.0) or 0.0)
        escaped_monotonic = float(state.get("escaped_monotonic", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    if observation_sequence <= fence_sequence or observed_monotonic <= escaped_monotonic:
        return False
    _SATURATION_ESCAPE.pop(bid, None)
    LOGGER.critical(
        "CAPITAL_V162_SATURATION_RECOVERED marker=%s broker=%s observation_sequence=%d "
        "prior_fence_sequence=%d newer_authoritative_observation=true escape_rearmed=true",
        MARKER,
        bid,
        observation_sequence,
        fence_sequence,
    )
    return True


def _fence_observation(guard: Any, broker_id: str, retired_sequence: int) -> int:
    bid = str(broker_id).strip().lower()
    sequence_map = getattr(guard, "_BROKER_SEQUENCE", None)
    current_sequence = int(sequence_map.get(bid, 0) or 0) if isinstance(sequence_map, dict) else 0
    fence_sequence = max(current_sequence, int(retired_sequence)) + 1
    if isinstance(sequence_map, dict):
        sequence_map[bid] = fence_sequence

    observations = getattr(guard, "_OBSERVATIONS", None)
    observation_cls = getattr(guard, "_Observation", None)
    observation_lock = getattr(guard, "_OBSERVATION_LOCK", None)
    if not isinstance(observations, dict) or observation_cls is None:
        return fence_sequence

    def apply() -> None:
        previous = observations.get(bid)
        if previous is None:
            values = (0.0, 0.0, 0.0, fence_sequence)
        else:
            values = (
                float(getattr(previous, "value", 0.0) or 0.0),
                float(getattr(previous, "observed_monotonic", 0.0) or 0.0),
                float(getattr(previous, "observed_epoch", 0.0) or 0.0),
                fence_sequence,
            )
        try:
            observations[bid] = observation_cls(
                value=values[0],
                observed_monotonic=values[1],
                observed_epoch=values[2],
                sequence=values[3],
            )
        except TypeError:
            observations[bid] = observation_cls(*values)

    if observation_lock is None:
        apply()
    else:
        with observation_lock:
            apply()
    return fence_sequence


def _fresh_broker_observation(guard: Any, v161: Any, broker_id: str, broker: Any) -> bool:
    """Require a real, timestamped broker observation before cap overrun recovery."""
    bid = str(broker_id).strip().lower()
    seed = getattr(v161, "_seed_fresh_broker_observation", None)
    if callable(seed) and broker is not None:
        try:
            seed(guard, bid, broker)
        except Exception:
            pass

    observations = getattr(guard, "_OBSERVATIONS", None)
    lock = getattr(guard, "_OBSERVATION_LOCK", None)
    if not isinstance(observations, dict):
        return False

    def read() -> Any:
        return observations.get(bid)

    observation = read() if lock is None else None
    if lock is not None:
        with lock:
            observation = read()
    if observation is None:
        return False
    try:
        value = float(getattr(observation, "value", 0.0) or 0.0)
        observed_mono = float(getattr(observation, "observed_monotonic", 0.0) or 0.0)
        ttl_getter = getattr(guard, "_freshness_ttl_seconds", None)
        ttl_s = float(ttl_getter()) if callable(ttl_getter) else 90.0
        age_s = max(0.0, time.monotonic() - observed_mono) if observed_mono > 0.0 else float("inf")
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(value > 0.0 and observed_mono > 0.0 and age_s <= max(1.0, ttl_s))


def _supersede_with_observation_fence(guard: Any, broker_map: dict[str, Any]) -> None:
    """v161 stale-flight rotation plus cache fencing and bounded saturation recovery."""
    v161 = _v161()
    in_flight = getattr(guard, "_IN_FLIGHT", None)
    in_flight_lock = getattr(guard, "_IN_FLIGHT_LOCK", None)
    if not isinstance(in_flight, dict) or in_flight_lock is None:
        return

    now = time.monotonic()
    with in_flight_lock:
        for broker_id, broker in broker_map.items():
            bid = str(broker_id).strip().lower()
            _escape_recovered(guard, bid)
            flight = in_flight.get(bid)
            if flight is None:
                continue
            thread = getattr(flight, "thread", None)
            is_alive = getattr(thread, "is_alive", None)
            if not callable(is_alive) or not bool(is_alive()):
                continue
            try:
                age_s = max(0.0, now - float(getattr(flight, "started_monotonic", now) or now))
            except (TypeError, ValueError):
                age_s = 0.0
            stale_after_s = float(v161._stale_flight_after_seconds(bid))
            if age_s < stale_after_s:
                continue

            orphans = v161._prune_orphans(bid)
            max_orphans = int(v161._max_orphaned_flights())
            # Once a previously allowed +1 recovery orphan has exited, permit a
            # later bounded recovery again. Never permit more than max+1 live
            # retired workers at one time.
            if len(orphans) <= max_orphans:
                _SATURATION_RECOVERY_USED.discard(bid)

            if len(orphans) >= max_orphans:
                can_recover = (
                    bid not in _SATURATION_RECOVERY_USED
                    and len(orphans) == max_orphans
                    and _fresh_broker_observation(guard, v161, bid, broker)
                )
                if not can_recover:
                    LOGGER.warning(
                        "CAPITAL_V162_STALE_FLIGHT_ROTATION_CAPPED marker=%s broker=%s age_s=%.2f "
                        "stale_after_s=%.2f live_orphans=%d max_orphans=%d current_reused=true "
                        "bounded_recovery_available=%s",
                hard_after_s = _hard_saturation_after_seconds(stale_after_s)
                escape_active = isinstance(_SATURATION_ESCAPE.get(bid), dict)
                if age_s < hard_after_s or escape_active:
                    LOGGER.warning(
                        "CAPITAL_V162_STALE_FLIGHT_ROTATION_CAPPED marker=%s broker=%s age_s=%.2f "
                        "stale_after_s=%.2f hard_after_s=%.2f live_orphans=%d max_orphans=%d "
                        "escape_active=%s current_reused=true",
                        MARKER,
                        bid,
                        age_s,
                        stale_after_s,
                        len(orphans),
                        max_orphans,
                        str(bid not in _SATURATION_RECOVERY_USED).lower(),
                        hard_after_s,
                        len(orphans),
                        max_orphans,
                        str(escape_active).lower(),
                    )
                    continue
                if in_flight.get(bid) is not flight:
                    continue

                retired_sequence = int(getattr(flight, "sequence", 0) or 0)
                fence_sequence = _fence_observation(guard, bid, retired_sequence)
                in_flight.pop(bid, None)
                orphans.append(flight)
                v161._ORPHANED_FLIGHTS[bid] = orphans
                _SATURATION_RECOVERY_USED.add(bid)
                LOGGER.critical(
                    "CAPITAL_V162_SATURATION_RECOVERY marker=%s base_marker=%s broker=%s "
                    "retired_sequence=%d fence_sequence=%d age_s=%.2f stale_after_s=%.2f "
                    "live_orphans=%d configured_max_orphans=%d bounded_overcommit=1 "
                    "fresh_broker_observation_required=true late_observation_fenced=true "
                    "new_fetch_allowed=true freshness_extended=false readiness_granted=false "
                    "safety_gates_bypassed=false",
                    SATURATION_MARKER,
                retired_sequence = int(getattr(flight, "sequence", 0) or 0)
                fence_sequence = _fence_observation(guard, bid, retired_sequence)
                in_flight.pop(bid, None)
                _SATURATION_ESCAPE[bid] = {
                    "flight": flight,
                    "fence_sequence": fence_sequence,
                    "escaped_monotonic": now,
                }
                LOGGER.critical(
                    "CAPITAL_V162_HARD_SATURATION_ESCAPE marker=%s broker=%s retired_sequence=%d "
                    "fence_sequence=%d age_s=%.2f stale_after_s=%.2f hard_after_s=%.2f "
                    "live_orphans=%d max_orphans=%d one_probe_only=true late_observation_fenced=true "
                    "new_fetch_allowed=true orphan_cap_unchanged=true freshness_extended=false "
                    "readiness_granted=false safety_gates_bypassed=false",
                    MARKER,
                    bid,
                    retired_sequence,
                    fence_sequence,
                    age_s,
                    stale_after_s,
                    hard_after_s,
                    len(orphans),
                    max_orphans,
                )
                continue

            if in_flight.get(bid) is not flight:
                continue

            retired_sequence = int(getattr(flight, "sequence", 0) or 0)
            fence_sequence = _fence_observation(guard, bid, retired_sequence)
            in_flight.pop(bid, None)
            orphans.append(flight)
            v161._ORPHANED_FLIGHTS[bid] = orphans
            LOGGER.critical(
                "CAPITAL_V162_STALE_FLIGHT_SUPERSEDED marker=%s broker=%s retired_sequence=%d "
                "fence_sequence=%d age_s=%.2f stale_after_s=%.2f live_orphans=%d "
                "late_observation_fenced=true new_fetch_allowed=true freshness_extended=false",
                MARKER,
                bid,
                retired_sequence,
                fence_sequence,
                age_s,
                stale_after_s,
                len(orphans),
            )


def install() -> bool:
    with _LOCK:
        v161 = _v161()
        current = getattr(v161, "_supersede_stale_guard_flights", None)
        if not callable(current):
            os.environ[_READY_FLAG] = "0"
            return False
        if not bool(getattr(current, _PATCH_ATTR, False)):
            @wraps(current)
            def fenced(guard: Any, broker_map: dict[str, Any]) -> None:
                _supersede_with_observation_fence(guard, broker_map)

            setattr(fenced, _PATCH_ATTR, True)
            setattr(fenced, "__wrapped__", current)
            v161._supersede_stale_guard_flights = fenced

        try:
            manifest = importlib.import_module("bot.runtime_release_manifest_patch")
            required = getattr(manifest, "_REQUIRED_FLAGS", None)
            if isinstance(required, dict):
                required["runtime_capital_late_observation_fence_v162"] = _READY_FLAG
        except Exception:
            os.environ[_READY_FLAG] = "0"
            return False

        os.environ[_READY_FLAG] = "1"
        LOGGER.critical(
            "RUNTIME_CAPITAL_LATE_OBSERVATION_FENCE_V162 marker=%s ready=true "
            "retired_worker_cache_write_fenced=true saturation_recovery_marker=%s "
            "bounded_overcommit_max=1 freshness_extended=false safety_gates_bypassed=false",
            "retired_worker_cache_write_fenced=true hard_saturation_escape_bounded=true "
            "orphan_cap_unchanged=true freshness_extended=false safety_gates_bypassed=false",
            MARKER,
            SATURATION_MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "SATURATION_MARKER",
    "install",
    "install_import_hook",
    "_fence_observation",
    "_fresh_broker_observation",
    "_supersede_with_observation_fence",
    "install",
    "install_import_hook",
    "_fence_observation",
    "_supersede_with_observation_fence",
    "_hard_saturation_after_seconds",
    "_escape_recovered",
]
