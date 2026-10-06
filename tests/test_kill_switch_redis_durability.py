from __future__ import annotations

import json
from pathlib import Path

from bot.kill_switch import KillSwitch


class FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def eval(self, script, numkeys, key, incoming_json):
        current = self.data.get(key)
        if current:
            try:
                decoded = json.loads(current)
            except Exception:
                decoded = None
            if isinstance(decoded, dict) and bool(decoded.get("is_active")):
                return current
        self.data[key] = incoming_json
        return incoming_json


class RacingFakeRedis(FakeRedis):
    def __init__(self, risk_payload):
        super().__init__()
        self.risk_payload = risk_payload
        self.injected = False

    def eval(self, script, numkeys, key, incoming_json):
        if not self.injected:
            self.data[key] = json.dumps(self.risk_payload, sort_keys=True)
            self.injected = True
        return super().eval(script, numkeys, key, incoming_json)


def test_durable_stop_reasserts_on_replacement_instance(tmp_path, monkeypatch):
    shared = FakeRedis()
    monkeypatch.setattr(KillSwitch, "_redis_client", lambda self: shared)

    first = KillSwitch(base_path=str(tmp_path / "first"))
    Path(first._base_path).mkdir(parents=True, exist_ok=True)
    # Rebuild paths because the directory is created after construction.
    first._kill_file = str(Path(first._base_path) / first.KILL_SWITCH_FILE)
    first._state_file = str(Path(first._base_path) / first.KILL_SWITCH_STATE_FILE)
    first.activate(
        "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=5.82%, equity=$732.99)",
        "GlobalDrawdownCircuitBreaker",
    )

    payload = json.loads(shared.get(first.DURABLE_REDIS_KEY))
    assert payload["is_active"] is True
    assert payload["source"] == "GlobalDrawdownCircuitBreaker"

    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second = KillSwitch(base_path=str(second_dir))
    assert second.is_active() is True
    status = second.get_status()
    assert status["recent_history"][-1]["source"] == "GlobalDrawdownCircuitBreaker"
    assert "drawdown=5.82%" in status["recent_history"][-1]["reason"]
    assert Path(second._kill_file).exists()


def test_deactivation_fails_closed_when_durable_clear_unavailable(tmp_path, monkeypatch):
    path = tmp_path / "node"
    path.mkdir()
    shared = FakeRedis()
    monkeypatch.setattr(KillSwitch, "_redis_client", lambda self: shared)
    ks = KillSwitch(base_path=str(path))
    ks.activate("risk halt", "GlobalDrawdownCircuitBreaker")
    assert ks.is_active() is True

    monkeypatch.setattr(ks, "_clear_durable_stop", lambda reason: False)
    result = ks.deactivate("attempted recovery")
    assert result is False
    assert ks.is_active() is True
    assert Path(ks._kill_file).exists()


def test_confirmed_durable_clear_allows_local_deactivation(tmp_path, monkeypatch):
    path = tmp_path / "node"
    path.mkdir()
    shared = FakeRedis()
    monkeypatch.setattr(KillSwitch, "_redis_client", lambda self: shared)
    ks = KillSwitch(base_path=str(path))
    ks.activate("risk halt", "GlobalDrawdownCircuitBreaker")
    ks.deactivate("verified recovery")

    assert ks.is_active() is False
    payload = json.loads(shared.get(ks.DURABLE_REDIS_KEY))
    assert payload["is_active"] is False
    assert not Path(ks._kill_file).exists()


def test_filesystem_replay_does_not_overwrite_durable_risk_cause(tmp_path, monkeypatch):
    path = tmp_path / "node"
    path.mkdir()
    shared = FakeRedis()
    monkeypatch.setattr(KillSwitch, "_redis_client", lambda self: shared)

    first = KillSwitch(base_path=str(path))
    first.activate(
        "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=20.31%, equity=$617.89)",
        "GlobalDrawdownCircuitBreaker",
    )
    original = json.loads(shared.get(first.DURABLE_REDIS_KEY))
    assert original["source"] == "GlobalDrawdownCircuitBreaker"

    # A new KillSwitch object on the same filesystem sees EMERGENCY_STOP first.
    # That restart/file replay must remain fail-closed locally without erasing
    # the original causal stop stored in durable Redis.
    replay = KillSwitch(base_path=str(path))
    assert replay.is_active() is True

    preserved = json.loads(shared.get(first.DURABLE_REDIS_KEY))
    assert preserved["is_active"] is True
    assert preserved["source"] == "GlobalDrawdownCircuitBreaker"
    assert "drawdown=20.31%" in preserved["reason"]



def test_atomic_filesystem_replay_cannot_overwrite_concurrent_risk_activation(tmp_path, monkeypatch):
    path = tmp_path / "node"
    path.mkdir()
    risk = {
        "is_active": True,
        "reason": "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=20.31%, equity=$617.89)",
        "source": "GlobalDrawdownCircuitBreaker",
        "timestamp": "2026-10-06T07:36:33+00:00",
        "schema": 1,
    }
    shared = RacingFakeRedis(risk)
    monkeypatch.setattr(KillSwitch, "_redis_client", lambda self: shared)

    ks = KillSwitch(base_path=str(path))
    ok = ks._persist_durable_stop(
        {
            "reason": "Kill switch file detected",
            "source": "FILE_SYSTEM",
            "timestamp": "2026-10-06T14:55:23.027303+00:00",
        }
    )

    assert ok is True
    durable = json.loads(shared.get(ks.DURABLE_REDIS_KEY))
    assert durable == risk
    assert durable["source"] == "GlobalDrawdownCircuitBreaker"
