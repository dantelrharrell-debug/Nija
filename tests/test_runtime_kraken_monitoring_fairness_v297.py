from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from bot import runtime_kraken_monitoring_fairness_v297_patch as v297


def _reset_flights() -> None:
    with v297._FLIGHT_LOCK:
        v297._BALANCE_FLIGHTS.clear()


def _wait_for_waiters(gate: v297._PriorityFairGate, count: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with gate._condition:
            if len(gate._waiters) >= count:
                return
        time.sleep(0.005)
    raise AssertionError(f"expected at least {count} queued gate waiters")


def test_priority_gate_preserves_fifo_within_routine_readers():
    gate = v297._PriorityFairGate("PLATFORM")
    order: list[str] = []
    gate.acquire()

    def worker(name: str) -> None:
        with gate:
            order.append(name)

    first = threading.Thread(target=worker, args=("first",))
    second = threading.Thread(target=worker, args=("second",))
    first.start()
    _wait_for_waiters(gate, 1)
    second.start()
    _wait_for_waiters(gate, 2)
    gate.release()

    first.join(timeout=2.0)
    second.join(timeout=2.0)
    assert not first.is_alive()
    assert not second.is_alive()
    assert order == ["first", "second"]


def test_authoritative_position_reader_overtakes_queued_routine_reader():
    gate = v297._PriorityFairGate("PLATFORM")
    order: list[str] = []
    gate.acquire()

    def routine() -> None:
        with gate:
            order.append("routine")

    def authoritative() -> None:
        state = v297._set_authoritative_priority(True)
        try:
            with gate:
                order.append("authoritative")
        finally:
            v297._restore_authoritative_priority(state)

    routine_thread = threading.Thread(target=routine)
    auth_thread = threading.Thread(target=authoritative)
    routine_thread.start()
    _wait_for_waiters(gate, 1)
    auth_thread.start()
    _wait_for_waiters(gate, 2)
    gate.release()

    routine_thread.join(timeout=2.0)
    auth_thread.join(timeout=2.0)
    assert not routine_thread.is_alive()
    assert not auth_thread.is_alive()
    assert order == ["authoritative", "routine"]


def test_priority_gate_remains_exclusive_under_concurrency():
    gate = v297._PriorityFairGate("PLATFORM")
    state_lock = threading.Lock()
    active = 0
    peak = 0
    barrier = threading.Barrier(5)

    def worker(index: int) -> None:
        nonlocal active, peak
        barrier.wait(timeout=2.0)
        priority_state = v297._set_authoritative_priority(index == 4)
        try:
            with gate:
                with state_lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.015)
                with state_lock:
                    active -= 1
        finally:
            v297._restore_authoritative_priority(priority_state)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    assert peak == 1
    assert active == 0


def test_balance_single_flight_executes_one_genuine_call_and_copies_results(monkeypatch):
    _reset_flights()
    monkeypatch.setattr(v297, "_balance_wait_s", lambda broker: 2.0)
    broker = SimpleNamespace(account_identifier="PLATFORM")
    call_lock = threading.Lock()
    calls = 0
    results: list[dict] = []
    barrier = threading.Barrier(4)

    def genuine_call():
        nonlocal calls
        with call_lock:
            calls += 1
        time.sleep(0.05)
        return {"error": [], "result": {"ZUSD": "12.34", "XETH": "0.01"}}

    def worker() -> None:
        barrier.wait(timeout=2.0)
        result = v297._coalesced_balance_call(broker, genuine_call)
        results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    assert calls == 1
    assert len(results) == 4
    assert all(result == results[0] for result in results)
    assert len({id(result) for result in results}) == 4
    results[0]["result"]["ZUSD"] = "changed"
    assert all(result["result"]["ZUSD"] == "12.34" for result in results[1:])


def test_balance_single_flight_propagates_owner_error_to_joiners(monkeypatch):
    _reset_flights()
    monkeypatch.setattr(v297, "_balance_wait_s", lambda broker: 2.0)
    broker = SimpleNamespace(account_identifier="PLATFORM")
    calls = 0
    call_lock = threading.Lock()
    errors: list[str] = []
    barrier = threading.Barrier(3)

    def genuine_call():
        nonlocal calls
        with call_lock:
            calls += 1
        time.sleep(0.04)
        raise RuntimeError("exchange_transport_failure")

    def worker() -> None:
        barrier.wait(timeout=2.0)
        try:
            v297._coalesced_balance_call(broker, genuine_call)
        except RuntimeError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    assert calls == 1
    assert errors == ["exchange_transport_failure"] * 3


def test_balance_flight_does_not_become_long_lived_cache(monkeypatch):
    _reset_flights()
    monkeypatch.setattr(v297, "_reuse_grace_s", lambda: 0.0)
    broker = SimpleNamespace(account_identifier="PLATFORM")
    calls = 0

    def genuine_call():
        nonlocal calls
        calls += 1
        return {"error": [], "result": {"ZUSD": str(calls)}}

    first = v297._coalesced_balance_call(broker, genuine_call)
    second = v297._coalesced_balance_call(broker, genuine_call)

    assert calls == 2
    assert first["result"]["ZUSD"] == "1"
    assert second["result"]["ZUSD"] == "2"


def test_balance_wait_budget_respects_existing_interval_without_changing_it(monkeypatch):
    broker = SimpleNamespace(account_identifier="PLATFORM")
    monkeypatch.setattr(v297, "_monitoring_interval_s", lambda broker: 60.0)
    monkeypatch.setattr(v297, "_transport_timeout_s", lambda broker: 12.0)
    assert v297._balance_wait_s(broker) == pytest.approx(162.0)
