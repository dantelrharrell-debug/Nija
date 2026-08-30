from __future__ import annotations

import sys
import threading
import time
import types


def _load(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_AUTHORITATIVE_POSITION_FLIGHT_MAX_AGE_S", "30")
    sys.modules.pop("bot.runtime_kraken_position_flight_recovery_v287_patch", None)
    from bot import runtime_kraken_position_flight_recovery_v287_patch as v287
    return v287


def test_stale_unfinished_flight_is_retired(monkeypatch):
    v287 = _load(monkeypatch)
    v286 = types.SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _AUTH_FLIGHTS={},
    )
    stale_event = threading.Event()
    stale = {
        "event": stale_event,
        "result": None,
        "error": None,
        "started_at": time.monotonic() - 60.0,
        "finished_at": 0.0,
    }
    v286._AUTH_FLIGHTS[123] = stale
    monkeypatch.setattr(v287, "_v286", lambda: v286)

    retired = v287._retire_stale_flights()

    assert retired == 1
    assert 123 not in v286._AUTH_FLIGHTS
    assert stale_event.is_set() is False


def test_recent_unfinished_flight_is_preserved(monkeypatch):
    v287 = _load(monkeypatch)
    v286 = types.SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _AUTH_FLIGHTS={},
    )
    recent = {
        "event": threading.Event(),
        "result": None,
        "error": None,
        "started_at": time.monotonic() - 5.0,
        "finished_at": 0.0,
    }
    v286._AUTH_FLIGHTS[456] = recent
    monkeypatch.setattr(v287, "_v286", lambda: v286)

    assert v287._retire_stale_flights() == 0
    assert v286._AUTH_FLIGHTS[456] is recent


def test_completed_flight_is_never_retired(monkeypatch):
    v287 = _load(monkeypatch)
    event = threading.Event()
    event.set()
    v286 = types.SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _AUTH_FLIGHTS={789: {
            "event": event,
            "result": [{"symbol": "BTC-USD", "quantity": 0.1}],
            "error": None,
            "started_at": time.monotonic() - 120.0,
            "finished_at": time.monotonic() - 100.0,
        }},
    )
    monkeypatch.setattr(v287, "_v286", lambda: v286)

    assert v287._retire_stale_flights() == 0
    assert 789 in v286._AUTH_FLIGHTS


def test_wrapper_retires_stale_before_delegating(monkeypatch):
    v287 = _load(monkeypatch)
    calls = []

    def original(broker):
        calls.append(broker)
        return [{"symbol": "BTC-USD", "quantity": 0.1}]

    v286 = types.SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _AUTH_FLIGHTS={321: {
            "event": threading.Event(),
            "result": None,
            "error": None,
            "started_at": time.monotonic() - 60.0,
            "finished_at": 0.0,
        }},
        _authoritative_positions=original,
    )
    monkeypatch.setattr(v287, "_v286", lambda: v286)

    assert v287._patch_authoritative_positions() is True
    broker = object()
    result = v286._authoritative_positions(broker)

    assert 321 not in v286._AUTH_FLIGHTS
    assert calls == [broker]
    assert result == [{"symbol": "BTC-USD", "quantity": 0.1}]


def test_live_micro_cap_worker_survives_legitimate_rate_wait(monkeypatch):
    v287 = _load(monkeypatch)

    class LiveThread:
        def is_alive(self):
            return True

    broker = object()
    flight = {
        "event": threading.Event(),
        "result": None,
        "error": None,
        "started_at": time.monotonic() - 100.0,
        "finished_at": 0.0,
        "thread": LiveThread(),
        "broker": broker,
    }
    v286 = types.SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _AUTH_FLIGHTS={654: flight},
    )
    monkeypatch.setattr(v287, "_v286", lambda: v286)
    monkeypatch.setattr(v287, "_monitoring_interval_s", lambda _broker: 60.0)

    assert v287._flight_hard_age_s(flight) == 180.0
    assert v287._retire_stale_flights() == 0
    assert v286._AUTH_FLIGHTS[654] is flight


def test_live_micro_cap_worker_retires_only_after_dynamic_budget(monkeypatch):
    v287 = _load(monkeypatch)

    class LiveThread:
        def is_alive(self):
            return True

    broker = object()
    flight = {
        "event": threading.Event(),
        "result": None,
        "error": None,
        "started_at": time.monotonic() - 181.0,
        "finished_at": 0.0,
        "thread": LiveThread(),
        "broker": broker,
    }
    v286 = types.SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _AUTH_FLIGHTS={987: flight},
    )
    monkeypatch.setattr(v287, "_v286", lambda: v286)
    monkeypatch.setattr(v287, "_monitoring_interval_s", lambda _broker: 60.0)

    assert v287._retire_stale_flights() == 1
    assert 987 not in v286._AUTH_FLIGHTS


def test_dead_worker_retires_without_waiting_full_rate_budget(monkeypatch):
    v287 = _load(monkeypatch)

    class DeadThread:
        def is_alive(self):
            return False

    broker = object()
    flight = {
        "event": threading.Event(),
        "result": None,
        "error": None,
        "started_at": time.monotonic() - 3.0,
        "finished_at": 0.0,
        "thread": DeadThread(),
        "broker": broker,
    }
    v286 = types.SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _AUTH_FLIGHTS={111: flight},
    )
    monkeypatch.setattr(v287, "_v286", lambda: v286)
    monkeypatch.setattr(v287, "_monitoring_interval_s", lambda _broker: 60.0)

    assert v287._retire_stale_flights() == 1
    assert 111 not in v286._AUTH_FLIGHTS
