from types import SimpleNamespace

import pytest

from bot import order_submission_deadline as deadline
from bot.execution_pipeline import ExecutionPipeline
from bot.broker_manager import KrakenBroker


def test_mutation_deadline_fails_closed_after_expiry(monkeypatch):
    now = {"value": 100.0}
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now["value"])

    with deadline.order_submission_deadline_scope(5.0):
        assert deadline.remaining_s() == pytest.approx(5.0)
        now["value"] = 106.0
        with pytest.raises(TimeoutError, match="order_submission_deadline_expired_before_addorder"):
            deadline.assert_mutation_deadline("AddOrder")


def test_caller_absolute_deadline_is_not_extended_by_worker_start(monkeypatch):
    now = {"value": 300.0}
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now["value"])
    caller_deadline = 305.0

    # Simulate the worker not beginning until after the caller's original
    # dispatch deadline. Passing the absolute value must fail immediately.
    now["value"] = 306.0
    with deadline.order_submission_deadline_scope(
        5.0,
        deadline_monotonic=caller_deadline,
    ):
        with pytest.raises(TimeoutError, match="order_submission_deadline_expired_before_addorder"):
            deadline.assert_mutation_deadline("AddOrder")


def test_no_deadline_preserves_existing_behavior():
    assert deadline.current_deadline_monotonic() == 0.0
    assert deadline.remaining_s() is None
    deadline.assert_mutation_deadline("AddOrder")


def test_heartbeat_gets_larger_but_bounded_ack_window(monkeypatch):
    pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
    pipeline._ack_timeout_s = 60.0

    ordinary = SimpleNamespace(strategy="APEX")
    heartbeat = SimpleNamespace(strategy="HEARTBEAT_TRADE")

    assert pipeline._dispatch_timeout_s(ordinary) == 60.0

    monkeypatch.setenv("NIJA_HEARTBEAT_ACK_TIMEOUT_S", "120")
    assert pipeline._dispatch_timeout_s(heartbeat) == 120.0

    monkeypatch.setenv("NIJA_HEARTBEAT_ACK_TIMEOUT_S", "999")
    assert pipeline._dispatch_timeout_s(heartbeat) == 180.0


def test_heartbeat_timeout_never_shortens_existing_ack_window(monkeypatch):
    pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
    pipeline._ack_timeout_s = 150.0
    heartbeat = SimpleNamespace(strategy="HEARTBEAT_TRADE_CLOSE")

    monkeypatch.setenv("NIJA_HEARTBEAT_ACK_TIMEOUT_S", "45")
    assert pipeline._dispatch_timeout_s(heartbeat) == 150.0


def test_expired_worker_cannot_reach_kraken_addorder(monkeypatch):
    now = {"value": 200.0}
    monkeypatch.setattr(deadline.time, "monotonic", lambda: now["value"])

    class FakeAPI:
        def __init__(self):
            self.calls = []

        def query_private(self, method, params):
            self.calls.append((method, dict(params or {})))
            return {"error": [], "result": {"txid": ["SHOULD-NOT-HAPPEN"]}}

    broker = KrakenBroker.__new__(KrakenBroker)
    broker._hard_stopped = False
    broker._hard_stop_reason = ""
    broker._gateway_url = ""
    broker._gateway_only_mode = False
    broker.api = FakeAPI()

    with deadline.order_submission_deadline_scope(1.0):
        now["value"] = 202.0
        with pytest.raises(TimeoutError, match="order_submission_deadline_expired_before_addorder"):
            broker._kraken_private_call("AddOrder", {"pair": "XETHZUSD"})

    assert broker.api.calls == []
