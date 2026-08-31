from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from bot import runtime_kraken_authoritative_snapshot_liveness_v330_patch as v330


def test_timeout_recovery_uses_actual_reused_flight_epoch(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    flight_started = time.monotonic() - 8.0
    flight = {
        "event": threading.Event(),
        "started_at": flight_started,
        "result": None,
        "error": None,
    }
    calls = []
    not_before_seen = []

    def original(_broker):
        calls.append("authoritative_wait")
        raise TimeoutError("old authoritative flight still pending")

    fake_v286 = SimpleNamespace(
        _authoritative_positions=original,
        _AUTH_FLIGHTS={id(broker): flight},
        _AUTH_LOCK=threading.RLock(),
    )

    # This observation represents a genuine same-credential Balance that
    # arrived after the underlying flight began but before the newest retry.
    observed_at = time.monotonic() - 2.0

    def fresh_observation(_broker, *, not_before):
        not_before_seen.append(not_before)
        assert not_before == pytest.approx(flight_started)
        assert observed_at >= not_before
        return {
            "response": {"error": [], "result": {"XXBT": "0.001"}},
            "observed_at": observed_at,
            "age_s": max(0.0, time.monotonic() - observed_at),
        }

    def rows_from_observation(_broker, observation):
        assert observation["response"]["result"]["XXBT"] == "0.001"
        return [{"symbol": "BTC-USD", "quantity": 0.001, "authoritative_balance": True}]

    fake_v312 = SimpleNamespace(
        _fresh_observation=fresh_observation,
        _rows_from_observation=rows_from_observation,
    )
    monkeypatch.setattr(v330, "_v286", lambda: fake_v286)
    monkeypatch.setattr(v330, "_v312", lambda: fake_v312)

    assert v330._patch_timeout_epoch_recovery() is True
    rows = fake_v286._authoritative_positions(broker)

    assert rows == [{"symbol": "BTC-USD", "quantity": 0.001, "authoritative_balance": True}]
    assert calls == ["authoritative_wait"]
    assert not_before_seen == [pytest.approx(flight_started)]
    assert fake_v286._AUTH_FLIGHTS[id(broker)] is flight
    assert flight["event"].is_set() is False


def test_timeout_without_genuine_same_flight_observation_remains_fail_closed(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    flight_started = time.monotonic() - 8.0
    flight = {"event": threading.Event(), "started_at": flight_started}
    calls = []

    def original(_broker):
        calls.append("authoritative_wait")
        raise TimeoutError("still pending")

    fake_v286 = SimpleNamespace(
        _authoritative_positions=original,
        _AUTH_FLIGHTS={id(broker): flight},
        _AUTH_LOCK=threading.RLock(),
    )
    fake_v312 = SimpleNamespace(
        _fresh_observation=lambda _broker, *, not_before: None,
        _rows_from_observation=lambda _broker, observation: pytest.fail("must not build rows"),
    )
    monkeypatch.setattr(v330, "_v286", lambda: fake_v286)
    monkeypatch.setattr(v330, "_v312", lambda: fake_v312)

    assert v330._patch_timeout_epoch_recovery() is True
    with pytest.raises(TimeoutError, match="still pending"):
        fake_v286._authoritative_positions(broker)

    assert calls == ["authoritative_wait"]
    assert fake_v286._AUTH_FLIGHTS[id(broker)] is flight
    assert flight["event"].is_set() is False


def _fake_v285(age_by_broker):
    def platform_candidates(_manager):
        return []

    def snapshot_status(broker):
        age_s, ready = age_by_broker[id(broker)]
        return ready, "current" if ready else "stale", (), age_s, 7

    return SimpleNamespace(
        _platform_candidates=platform_candidates,
        _snapshot_status=snapshot_status,
        _refresh_interval_s=lambda: 49.5,
        _connected=lambda broker: bool(getattr(broker, "connected", False)),
        _label=lambda value: str(value).lower(),
    )


def test_proactive_refresh_adds_only_current_aged_kraken(monkeypatch):
    kraken = SimpleNamespace(connected=True)
    coinbase = SimpleNamespace(connected=True)
    fake_v285 = _fake_v285({id(kraken): (50.0, True), id(coinbase): (50.0, True)})
    manager = SimpleNamespace(platform_brokers={"kraken": kraken, "coinbase": coinbase})
    monkeypatch.setattr(v330, "_v285", lambda: fake_v285)

    assert v330._patch_proactive_kraken_refresh() is True
    assert fake_v285._platform_candidates(manager) == [("kraken", kraken)]


def test_proactive_refresh_does_not_add_young_stale_or_disconnected_kraken(monkeypatch):
    young = SimpleNamespace(connected=True)
    stale = SimpleNamespace(connected=True)
    disconnected = SimpleNamespace(connected=False)
    fake_v285 = _fake_v285(
        {
            id(young): (40.0, True),
            id(stale): (70.0, False),
            id(disconnected): (70.0, True),
        }
    )
    manager = SimpleNamespace(
        platform_brokers={"kraken": young, "kraken_stale": stale, "kraken_disconnected": disconnected}
    )
    monkeypatch.setattr(v330, "_v285", lambda: fake_v285)

    assert v330._patch_proactive_kraken_refresh() is True
    assert fake_v285._platform_candidates(manager) == []
