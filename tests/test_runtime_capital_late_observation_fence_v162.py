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


def _flight(sequence: int, age_s: float = 60.0):
    return SimpleNamespace(
        thread=_AliveThread(),
        sequence=sequence,
        started_monotonic=time.monotonic() - age_s,
        timeout_s=75.0,
    )


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
    flight = _flight(5)
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


def test_saturation_recovery_allows_one_bounded_overcap_with_fresh_evidence(monkeypatch):
    v162._SATURATION_RECOVERY_USED.clear()
    current = _flight(8, 120.0)
    orphan_a = _flight(6, 180.0)
    orphan_b = _flight(7, 150.0)
    previous = Observation(
        242.0,
        time.monotonic() - 5.0,
        time.time() - 5.0,
        8,
    )
    guard = SimpleNamespace(
        _IN_FLIGHT={"kraken": current},
        _IN_FLIGHT_LOCK=threading.Lock(),
        _BROKER_SEQUENCE={"kraken": 8},
        _OBSERVATIONS={"kraken": previous},
        _OBSERVATION_LOCK=threading.Lock(),
        _Observation=Observation,
        _freshness_ttl_seconds=lambda: 90.0,
    )
    orphans = [orphan_a, orphan_b]
    fake_v161 = SimpleNamespace(
        _stale_flight_after_seconds=lambda broker_id: 45.0,
        _prune_orphans=lambda broker_id: list(orphans),
        _max_orphaned_flights=lambda: 2,
        _ORPHANED_FLIGHTS={"kraken": list(orphans)},
        _seed_fresh_broker_observation=lambda guard, bid, broker: True,
    )
    monkeypatch.setattr(v162, "_v161", lambda: fake_v161)

    v162._supersede_with_observation_fence(guard, {"kraken": object()})

    assert "kraken" not in guard._IN_FLIGHT
    assert guard._BROKER_SEQUENCE["kraken"] == 9
    assert guard._OBSERVATIONS["kraken"].sequence == 9
    assert fake_v161._ORPHANED_FLIGHTS["kraken"] == [orphan_a, orphan_b, current]
    assert "kraken" in v162._SATURATION_RECOVERY_USED


def test_saturation_recovery_refuses_unbounded_second_overcap(monkeypatch):
    v162._SATURATION_RECOVERY_USED.clear()
    v162._SATURATION_RECOVERY_USED.add("kraken")
    current = _flight(9, 120.0)
    orphans = [_flight(6), _flight(7), _flight(8)]
    previous = Observation(242.0, time.monotonic() - 5.0, time.time() - 5.0, 9)
    guard = SimpleNamespace(
        _IN_FLIGHT={"kraken": current},
        _IN_FLIGHT_LOCK=threading.Lock(),
        _BROKER_SEQUENCE={"kraken": 9},
        _OBSERVATIONS={"kraken": previous},
        _OBSERVATION_LOCK=threading.Lock(),
        _Observation=Observation,
        _freshness_ttl_seconds=lambda: 90.0,
    )
    fake_v161 = SimpleNamespace(
        _stale_flight_after_seconds=lambda broker_id: 45.0,
        _prune_orphans=lambda broker_id: list(orphans),
        _max_orphaned_flights=lambda: 2,
        _ORPHANED_FLIGHTS={"kraken": list(orphans)},
        _seed_fresh_broker_observation=lambda guard, bid, broker: True,
    )
    monkeypatch.setattr(v162, "_v161", lambda: fake_v161)

    v162._supersede_with_observation_fence(guard, {"kraken": object()})

    assert guard._IN_FLIGHT["kraken"] is current
    assert guard._BROKER_SEQUENCE["kraken"] == 9
    assert fake_v161._ORPHANED_FLIGHTS["kraken"] == orphans


def test_saturation_recovery_requires_fresh_observation(monkeypatch):
    v162._SATURATION_RECOVERY_USED.clear()
    current = _flight(8, 120.0)
    orphans = [_flight(6), _flight(7)]
    stale = Observation(242.0, time.monotonic() - 200.0, time.time() - 200.0, 8)
    guard = SimpleNamespace(
        _IN_FLIGHT={"kraken": current},
        _IN_FLIGHT_LOCK=threading.Lock(),
        _BROKER_SEQUENCE={"kraken": 8},
        _OBSERVATIONS={"kraken": stale},
        _OBSERVATION_LOCK=threading.Lock(),
        _Observation=Observation,
        _freshness_ttl_seconds=lambda: 90.0,
    )
    fake_v161 = SimpleNamespace(
        _stale_flight_after_seconds=lambda broker_id: 45.0,
        _prune_orphans=lambda broker_id: list(orphans),
        _max_orphaned_flights=lambda: 2,
        _ORPHANED_FLIGHTS={"kraken": list(orphans)},
        _seed_fresh_broker_observation=lambda guard, bid, broker: False,
    )
    monkeypatch.setattr(v162, "_v161", lambda: fake_v161)

    v162._supersede_with_observation_fence(guard, {"kraken": object()})

    assert guard._IN_FLIGHT["kraken"] is current
    assert guard._BROKER_SEQUENCE["kraken"] == 8
    assert "kraken" not in v162._SATURATION_RECOVERY_USED
