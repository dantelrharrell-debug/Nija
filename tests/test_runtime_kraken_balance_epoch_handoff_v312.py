from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from bot import runtime_kraken_balance_epoch_handoff_v312_patch as v312


@pytest.fixture(autouse=True)
def _clear_observations(monkeypatch):
    with v312._LOCK:
        v312._OBSERVATIONS.clear()
    monkeypatch.setattr(v312, "_credential_key", lambda _broker: ("credential:test", True))
    yield
    with v312._LOCK:
        v312._OBSERVATIONS.clear()


def _valid_balance():
    return {"error": [], "result": {"XXBT": "0.001", "ZUSD": "10.0"}}


def test_observation_requires_valid_authenticated_same_credential(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")

    assert v312._record_observation(broker, _valid_balance()) is True
    observation = v312._fresh_observation(broker, not_before=time.monotonic() - 0.5)
    assert observation is not None
    assert observation["response"]["result"]["XXBT"] == "0.001"

    monkeypatch.setattr(v312, "_credential_key", lambda _broker: ("object:unproven", False))
    assert v312._record_observation(broker, _valid_balance()) is False
    assert v312._record_observation(broker, {"error": ["EGeneral:fail"], "result": {}}) is False


def test_stale_or_pre_epoch_observation_is_rejected(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    assert v312._record_observation(broker, _valid_balance()) is True

    with v312._LOCK:
        row = v312._OBSERVATIONS["credential:test"]
        row["observed_at"] = time.monotonic() - 31.0
    assert v312._fresh_observation(broker, not_before=0.0) is None

    assert v312._record_observation(broker, _valid_balance()) is True
    observed_at = v312._OBSERVATIONS["credential:test"]["observed_at"]
    monkeypatch.setattr(v312, "_epoch_slack_s", lambda: 0.0)
    assert v312._fresh_observation(broker, not_before=observed_at + 0.01) is None


def test_timeout_recovery_uses_balance_observed_during_current_attempt(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    recorded = []

    def original(_broker):
        # Represents a newer successful capital/monitoring Balance completing
        # while the caller is waiting on an older v286 position flight.
        assert v312._record_observation(broker, _valid_balance()) is True
        raise TimeoutError("old authoritative flight still pending")

    def build_rows(_broker, result):
        assert result["XXBT"] == "0.001"
        return [{"symbol": "BTC-USD", "quantity": 0.001, "authoritative_balance": True}]

    def record_snapshot(_broker, rows):
        recorded.append(list(rows))
        return True

    fake_v286 = SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _authoritative_positions=original,
        _build_authoritative_rows=build_rows,
        _record_snapshot_success=record_snapshot,
    )
    monkeypatch.setattr(v312, "_v286", lambda: fake_v286)

    assert v312._patch_v286_authoritative_positions() is True
    rows = fake_v286._authoritative_positions(broker)

    assert rows == [{"symbol": "BTC-USD", "quantity": 0.001, "authoritative_balance": True}]
    assert recorded == [rows]


def test_non_timeout_position_failure_remains_fail_closed(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")

    def original(_broker):
        raise RuntimeError("exchange payload invalid")

    fake_v286 = SimpleNamespace(_AUTH_LOCK=threading.RLock(), _authoritative_positions=original)
    monkeypatch.setattr(v312, "_v286", lambda: fake_v286)

    assert v312._patch_v286_authoritative_positions() is True
    with pytest.raises(RuntimeError, match="exchange payload invalid"):
        fake_v286._authoritative_positions(broker)


def test_pre_read_handoff_publishes_completion_under_snapshot_writer_lock(monkeypatch):
    broker = SimpleNamespace(account_identifier="fixture")
    lock = threading.RLock()
    event = threading.Event()
    flight = {"started_at": time.monotonic(), "event": event}
    rows = [{"symbol": "BTC-USD", "quantity": 0.001}]
    assert v312._record_observation(broker, _valid_balance())
    fallback = []

    class SnapshotRows(list):
        def __init__(self, values, generation):
            super().__init__(values)
            self.generation = generation

    def recorder(_broker, result):
        assert result == rows
        return 1

    observed_locked = []
    original_set = event.set

    def check_then_signal():
        def probe():
            acquired = lock.acquire(blocking=False)
            observed_locked.append(not acquired)
            if acquired:
                lock.release()

        t = threading.Thread(target=probe)
        t.start()
        t.join(2)
        assert not t.is_alive()
        original_set()

    monkeypatch.setattr(event, "set", check_then_signal)
    fake_v286 = SimpleNamespace(
        _AUTH_LOCK=lock,
        _PublishedBalanceRows=SnapshotRows,
        _finish_auth_flight=lambda *_: fallback.append(True),
        _build_authoritative_rows=lambda *_: rows,
        _record_snapshot_success=recorder,
    )
    monkeypatch.setattr(v312, "_v286", lambda: fake_v286)
    assert v312._patch_v286_finish_flight()
    fake_v286._finish_auth_flight(flight, broker)
    assert not fallback
    assert event.is_set()
    assert observed_locked == [True]
    assert isinstance(flight["result"], SnapshotRows)
    assert flight["result"].generation == 1
    assert flight["result"] == rows


def test_pre_read_handoff_falls_back_when_observation_changes_during_valuation(monkeypatch):
    broker = SimpleNamespace(account_identifier="fixture")
    flight = {"started_at": time.monotonic(), "event": threading.Event()}
    assert v312._record_observation(broker, _valid_balance())
    fallback = []
    recorded = []

    def build_rows(_broker, _result):
        assert v312._record_observation(broker, {"error": [], "result": {"XXBT": "2"}})
        return [{"symbol": "BTC-USD", "quantity": 0.001}]

    fake_v286 = SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _finish_auth_flight=lambda *_: fallback.append(True),
        _build_authoritative_rows=build_rows,
        _record_snapshot_success=lambda *_: recorded.append(True),
    )
    monkeypatch.setattr(v312, "_v286", lambda: fake_v286)
    assert v312._patch_v286_finish_flight()
    fake_v286._finish_auth_flight(flight, broker)
    assert fallback == [True]
    assert not recorded
    assert not flight["event"].is_set()


@pytest.mark.parametrize("change", ["generation", "failure", "observation"])
def test_timeout_recovery_preserves_timeout_if_valuation_races_with_new_evidence(monkeypatch, change):
    broker = SimpleNamespace(account_identifier="fixture")
    timeout = TimeoutError("authoritative flight pending")
    publications = []

    def original(_broker):
        assert v312._record_observation(broker, _valid_balance())
        raise timeout

    def build_rows(_broker, _result):
        if change == "generation":
            broker._nija_authoritative_position_snapshot_generation_v285 = 1
        elif change == "failure":
            broker._nija_authoritative_position_failure_serial_v286 = 1
        else:
            assert v312._record_observation(broker, _valid_balance())
        return [{"symbol": "BTC-USD", "quantity": 0.001}]

    fake_v286 = SimpleNamespace(
        _AUTH_LOCK=threading.RLock(),
        _authoritative_positions=original,
        _build_authoritative_rows=build_rows,
        _record_snapshot_success=lambda *_: publications.append(True),
    )
    monkeypatch.setattr(v312, "_v286", lambda: fake_v286)
    assert v312._patch_v286_authoritative_positions()

    with pytest.raises(TimeoutError) as raised:
        fake_v286._authoritative_positions(broker)
    assert raised.value is timeout
    assert not publications
