from __future__ import annotations

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

    fake_v286 = SimpleNamespace(_authoritative_positions=original)
    monkeypatch.setattr(v312, "_v286", lambda: fake_v286)

    assert v312._patch_v286_authoritative_positions() is True
    with pytest.raises(RuntimeError, match="exchange payload invalid"):
        fake_v286._authoritative_positions(broker)
