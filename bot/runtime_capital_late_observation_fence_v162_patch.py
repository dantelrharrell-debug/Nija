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

No capital value is invented, no stale value is refreshed, and no trading gate
is bypassed.
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
_PATCH_ATTR = "_nija_runtime_capital_late_observation_fence_v162"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_LATE_OBSERVATION_FENCE_V162_READY"
_LOCK = threading.RLock()


def _v161():
    return importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")


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


def _supersede_with_observation_fence(guard: Any, broker_map: dict[str, Any]) -> None:
    """v161 stale-flight rotation plus a cache-generation fence."""
    v161 = _v161()
    in_flight = getattr(guard, "_IN_FLIGHT", None)
    in_flight_lock = getattr(guard, "_IN_FLIGHT_LOCK", None)
    if not isinstance(in_flight, dict) or in_flight_lock is None:
        return

    now = time.monotonic()
    with in_flight_lock:
        for broker_id in broker_map:
            bid = str(broker_id).strip().lower()
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
            if len(orphans) >= max_orphans:
                LOGGER.warning(
                    "CAPITAL_V162_STALE_FLIGHT_ROTATION_CAPPED marker=%s broker=%s age_s=%.2f "
                    "stale_after_s=%.2f live_orphans=%d max_orphans=%d current_reused=true",
                    MARKER,
                    bid,
                    age_s,
                    stale_after_s,
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
            "retired_worker_cache_write_fenced=true freshness_extended=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_fence_observation", "_supersede_with_observation_fence"]
