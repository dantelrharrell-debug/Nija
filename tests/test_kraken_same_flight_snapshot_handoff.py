import logging
import threading
import time

import pytest

from bot import position_sync_failure_truth_v98_patch as v98
from bot import runtime_authoritative_position_coverage_v285_patch as v285
from bot import runtime_kraken_balance_epoch_handoff_v312_patch as v312
from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286


class _FakeKraken:
    broker_type = "kraken"
    connected = True
    account_identifier = "fixture"

    def __init__(self, worker_error=False):
        self.worker_started = threading.Event()
        self.worker_release = threading.Event()
        self.calls = []
        self.worker_error = worker_error

    def _kraken_private_call(self, method, **kwargs):
        self.calls.append(method)
        self.worker_started.set()
        if not self.worker_release.wait(3):
            raise RuntimeError("fixture worker release timeout")
        if self.worker_error:
            return {"error": ["fixture_balance_denied"]}
        return {"result": {"XXBT": "2", "XETH": "3"}, "error": []}


def _race(monkeypatch, *, finish_worker=True, before_check=None, worker_error=False):
    broker = _FakeKraken(worker_error)
    monkeypatch.setenv("NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY", "1")
    monkeypatch.setattr(v286, "_AUTH_FLIGHTS", {})
    monkeypatch.setattr(v286, "_cached_price", lambda *_: 10.0)
    observed = {"result": {"XXBT": "1", "XETH": "3"}, "error": []}

    def fresh_observation(real, *, not_before):
        assert real is broker
        assert broker.worker_started.wait(3)
        return {"response": observed, "observed_at": time.monotonic(), "age_s": 0}

    monkeypatch.setattr(v312, "_fresh_observation", fresh_observation)
    proxy = v286._KrakenAuthoritativeProxy(broker)
    original_get = type(proxy).get_positions

    def deterministic_get(self, *args, **kwargs):
        result = original_get(self, *args, **kwargs)
        flight = v286._AUTH_FLIGHTS[id(broker)]
        if finish_worker:
            broker.worker_release.set()
            assert flight["event"].wait(3)
        if before_check:
            before_check(broker, result)
        return result

    monkeypatch.setattr(type(proxy), "get_positions", deterministic_get)
    return broker, v98._FetchProofProxy(proxy)


def test_completed_same_flight_worker_snapshot_is_checked_exactly(monkeypatch, caplog):
    broker, proxy = _race(monkeypatch)
    caplog.set_level(logging.WARNING)
    result = proxy.get_positions()
    assert broker.calls == ["Balance"]
    assert proxy.fetch_ok is True
    assert tuple(result) == broker._nija_authoritative_position_raw_rows_v286
    assert {row["symbol"]: row["quantity"] for row in result} == {"BTC-USD": 2, "ETH-USD": 3}
    assert broker._nija_authoritative_position_raw_generation_v286 == 2
    assert v285._snapshot_status(broker)[4] == 2
    assert "raw_rows_mismatch" not in caplog.text


@pytest.mark.parametrize("negative_case", ["unrelated", "tampered", "expired", "failed", "different_broker"])
def test_cannot_substitute_unproven_worker(monkeypatch, negative_case):
    def before_check(real, result):
        if negative_case == "unrelated":
            rows = [dict(row) for row in real._nija_authoritative_position_raw_rows_v286]
            rows[0]["quantity"] = 99
            v286._record_snapshot_success(real, rows)
        elif negative_case == "tampered":
            flight = v286._AUTH_FLIGHTS[id(real)]
            flight["result"][0]["quantity"] = 99
        elif negative_case == "expired":
            real._nija_authoritative_position_snapshot_at_monotonic_v285 -= 10000
        elif negative_case == "different_broker":
            result.broker = _FakeKraken()

    broker, proxy = _race(monkeypatch, before_check=before_check, worker_error=negative_case == "failed")
    with pytest.raises(RuntimeError, match="authoritative snapshot publication rejected"):
        proxy.get_positions()
    assert broker.calls == ["Balance"]
    assert proxy.fetch_ok is False


def test_current_handoff_does_not_wait_for_the_worker(monkeypatch):
    broker, proxy = _race(monkeypatch, finish_worker=False)
    try:
        result = proxy.get_positions()
        assert broker.calls == ["Balance"]
        assert proxy.fetch_ok is True
        assert tuple(result) == broker._nija_authoritative_position_raw_rows_v286
        assert {row["symbol"]: row["quantity"] for row in result} == {"BTC-USD": 1, "ETH-USD": 3}
        assert broker._nija_authoritative_position_raw_generation_v286 == 1
        assert not v286._AUTH_FLIGHTS[id(broker)]["event"].is_set()
    finally:
        broker.worker_release.set()
        assert v286._AUTH_FLIGHTS[id(broker)]["event"].wait(3)
