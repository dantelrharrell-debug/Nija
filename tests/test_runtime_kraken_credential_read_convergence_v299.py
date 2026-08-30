from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from bot import runtime_kraken_credential_read_convergence_v299_patch as v299


class _Broker:
    def __init__(self, key: str | None, account: str) -> None:
        self.api = SimpleNamespace(key=key) if key is not None else SimpleNamespace()
        self.account_identifier = account


def _reset_state() -> None:
    with v299._LOCK:
        v299._GATES.clear()
    with v299._FLIGHT_LOCK:
        v299._BALANCE_FLIGHTS.clear()


def test_same_credential_uses_same_coordination_key_and_gate():
    _reset_state()
    a = _Broker("same-secret-key", "PLATFORM-A")
    b = _Broker("same-secret-key", "PLATFORM-B")

    key_a, proven_a = v299._coordination_key(a)
    key_b, proven_b = v299._coordination_key(b)

    assert proven_a is True
    assert proven_b is True
    assert key_a == key_b
    assert key_a.startswith("credential:")
    assert v299._shared_monitoring_gate(a) is v299._shared_monitoring_gate(b)


def test_distinct_credentials_remain_independent():
    _reset_state()
    a = _Broker("key-one", "ONE")
    b = _Broker("key-two", "TWO")

    assert v299._coordination_key(a) != v299._coordination_key(b)
    assert v299._shared_monitoring_gate(a) is not v299._shared_monitoring_gate(b)


def test_unproven_credentials_fall_back_to_object_local_scope():
    _reset_state()
    a = _Broker(None, "A")
    b = _Broker(None, "B")

    key_a, proven_a = v299._coordination_key(a)
    key_b, proven_b = v299._coordination_key(b)

    assert proven_a is False
    assert proven_b is False
    assert key_a != key_b
    assert key_a.startswith("object:")
    assert v299._shared_monitoring_gate(a) is not v299._shared_monitoring_gate(b)


def test_same_credential_balance_calls_coalesce_across_broker_objects(monkeypatch):
    _reset_state()
    monkeypatch.setattr(v299, "_balance_wait_s", lambda broker: 2.0)
    monkeypatch.setattr(v299, "_reuse_grace_s", lambda: 0.05)

    a = _Broker("shared-key", "A")
    b = _Broker("shared-key", "B")
    owner_started = threading.Event()
    owner_release = threading.Event()
    owner_calls = []
    duplicate_calls = []
    results: list[dict] = []

    def owner_call():
        owner_calls.append(1)
        owner_started.set()
        assert owner_release.wait(1.0)
        return {"error": [], "result": {"XETH": "1.25"}}

    def duplicate_call():
        duplicate_calls.append(1)
        return {"error": [], "result": {"XETH": "999"}}

    first = threading.Thread(
        target=lambda: results.append(v299._credential_balance_call(a, owner_call))
    )
    second = threading.Thread(
        target=lambda: results.append(v299._credential_balance_call(b, duplicate_call))
    )

    first.start()
    assert owner_started.wait(1.0)
    second.start()
    time.sleep(0.05)
    owner_release.set()
    first.join(1.0)
    second.join(1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(owner_calls) == 1
    assert duplicate_calls == []
    assert len(results) == 2
    assert results[0] == results[1] == {"error": [], "result": {"XETH": "1.25"}}

    # Consumers must not share mutable result objects.
    results[0]["result"]["XETH"] = "changed"
    assert results[1]["result"]["XETH"] == "1.25"


def test_owner_error_propagates_to_same_credential_waiter(monkeypatch):
    _reset_state()
    monkeypatch.setattr(v299, "_balance_wait_s", lambda broker: 2.0)
    monkeypatch.setattr(v299, "_reuse_grace_s", lambda: 0.05)

    a = _Broker("shared-key", "A")
    b = _Broker("shared-key", "B")
    owner_started = threading.Event()
    owner_release = threading.Event()
    duplicate_calls = []
    errors: list[BaseException] = []

    def owner_call():
        owner_started.set()
        assert owner_release.wait(1.0)
        raise RuntimeError("genuine-balance-failure")

    def duplicate_call():
        duplicate_calls.append(1)
        return {"error": [], "result": {}}

    def invoke(broker, call):
        try:
            v299._credential_balance_call(broker, call)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=invoke, args=(a, owner_call))
    second = threading.Thread(target=invoke, args=(b, duplicate_call))
    first.start()
    assert owner_started.wait(1.0)
    second.start()
    time.sleep(0.05)
    owner_release.set()
    first.join(1.0)
    second.join(1.0)

    assert duplicate_calls == []
    assert len(errors) == 2
    assert all(isinstance(exc, RuntimeError) for exc in errors)
    assert all("genuine-balance-failure" in str(exc) for exc in errors)


def test_completed_flight_is_not_a_long_lived_cache(monkeypatch):
    _reset_state()
    monkeypatch.setattr(v299, "_balance_wait_s", lambda broker: 1.0)
    monkeypatch.setattr(v299, "_reuse_grace_s", lambda: 0.01)

    broker = _Broker("shared-key", "A")
    calls = []

    def call():
        calls.append(len(calls) + 1)
        return {"error": [], "result": {"n": calls[-1]}}

    first = v299._credential_balance_call(broker, call)
    time.sleep(0.03)
    second = v299._credential_balance_call(broker, call)

    assert first["result"]["n"] == 1
    assert second["result"]["n"] == 2
    assert len(calls) == 2


def test_patch_surfaces_replace_v286_gate_and_v297_coalescer(monkeypatch):
    _reset_state()
    v286 = v299._v286()
    v297 = v299._v297()

    original_gate = v286._instance_rate_gate
    original_balance = v297._coalesced_balance_call

    def sentinel_gate(broker):
        return object()

    def sentinel_balance(broker, call):
        return call()

    monkeypatch.setattr(v286, "_instance_rate_gate", sentinel_gate)
    monkeypatch.setattr(v297, "_coalesced_balance_call", sentinel_balance)

    assert v299._patch_monitoring_gate() is True
    assert v299._patch_balance_coalescer() is True
    assert bool(getattr(v286._instance_rate_gate, v299._GATE_PATCH_ATTR, False))
    assert bool(getattr(v297._coalesced_balance_call, v299._BALANCE_PATCH_ATTR, False))

    # Restore explicit originals before monkeypatch teardown so wrapper chains in
    # this test process do not retain the temporary sentinel functions.
    v286._instance_rate_gate = original_gate
    v297._coalesced_balance_call = original_balance
