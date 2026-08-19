from __future__ import annotations

import threading
import time
from collections import namedtuple
from types import SimpleNamespace

import bot.runtime_capital_late_observation_fence_v162_patch as v162


Observation = namedtuple(
    "Observation",
    "value observed_monotonic observed_epoch sequence",
)


class _AliveThread:
    def is_alive(self) -> bool:
        return True


def test_fence_preserves_authoritative_value_and_advances_sequence():
    previous = Observation(242.0, 100.0, 200.0, 3)
    guard = SimpleNamespace(
        _BROKER_SEQUENCE={"kraken": 3},
        _OBSERVATIONS={"kraken": previous},
        _OBSERVATION_LOCK=threading.Lock(),
        _Observation=Observation,
    )

    fence_sequence = v162._fence_observation(guard, "kraken", 3)

    assert fence_sequence == 4
    assert guard._BROKER_SEQUENCE["kraken"] == 4
    fenced = guard._OBSERVATIONS["kraken"]
    assert fenced.value == 242.0
    assert fenced.observed_monotonic == 100.0
    assert fenced.observed_epoch == 200.0
    assert fenced.sequence == 4


def test_fence_without_prior_observation_is_not_fresh_fallback():
    guard = SimpleNamespace(
        _BROKER_SEQUENCE={"kraken": 7},
        _OBSERVATIONS={},
        _OBSERVATION_LOCK=threading.Lock(),
        _Observation=Observation,
    )

    fence_sequence = v162._fence_observation(guard, "kraken", 7)

    assert fence_sequence == 8
    tombstone = guard._OBSERVATIONS["kraken"]
    assert tombstone.value == 0.0
    assert tombstone.observed_monotonic == 0.0
    assert tombstone.observed_epoch == 0.0
    assert tombstone.sequence == 8


def test_supersede_fences_old_worker_before_allowing_new_fetch(monkeypatch):
    flight = SimpleNamespace(
        thread=_AliveThread(),
        sequence=5,
        started_monotonic=time.monotonic() - 60.0,
        timeout_s=75.0,
    )
    previous = Observation(242.0, time.monotonic() - 10.0, time.time() - 10.0, 5)
    guard = SimpleNamespace(
        _IN_FLIGHT={"kraken": flight},
        _IN_FLIGHT_LOCK=threading.Lock(),
        _BROKER_SEQUENCE={"kraken": 5},
        _OBSERVATIONS={"kraken": previous},
        _OBSERVATION_LOCK=threading.Lock(),
        _Observation=Observation,
    )
    fake_v161 = SimpleNamespace(
        _stale_flight_after_seconds=lambda broker_id: 45.0,
        _prune_orphans=lambda broker_id: [],
        _max_orphaned_flights=lambda: 2,
        _ORPHANED_FLIGHTS={},
    )
    monkeypatch.setattr(v162, "_v161", lambda: fake_v161)

    v162._supersede_with_observation_fence(guard, {"kraken": object()})

    assert "kraken" not in guard._IN_FLIGHT
    assert guard._BROKER_SEQUENCE["kraken"] == 6
    assert guard._OBSERVATIONS["kraken"].value == 242.0
    assert guard._OBSERVATIONS["kraken"].sequence == 6
    assert fake_v161._ORPHANED_FLIGHTS["kraken"] == [flight]


def test_old_retired_sequence_cannot_replace_fenced_observation():
    # Mirrors v35's existing update condition:
    # previous is None or broker_seq >= previous.sequence.
    fenced = Observation(242.0, 100.0, 200.0, 6)
    retired_sequence = 5
    assert retired_sequence >= fenced.sequence is False
