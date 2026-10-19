from __future__ import annotations

import importlib.util
import threading
import time
import sys
from pathlib import Path

PATCH_PATH = Path(__file__).resolve().parents[1] / "capital_refresh_stall_guard_v35.py"
spec = importlib.util.spec_from_file_location("capital_v36_under_test", PATCH_PATH)
assert spec and spec.loader
cap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cap
spec.loader.exec_module(cap)


def _reset():
    cap._IN_FLIGHT.clear(); cap._BROKER_SEQUENCE.clear(); cap._OBSERVATIONS.clear(); cap._LAST_TIMEOUT_LOGGED.clear(); cap._WAS_TIMING_OUT.clear(); cap._begin_refresh_context()


def test_reused_inflight_fetch_reuses_same_queue(monkeypatch):
    _reset(); monkeypatch.setenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "2"); gate = threading.Event()
    class Broker:
        def get_account_balance(self): gate.wait(1.0); return 123.45
    broker = Broker(); first = cap._BalanceFetchBatch({"coinbase": broker}); second = cap._BalanceFetchBatch({"coinbase": broker})
    assert first._flights["coinbase"].sequence == second._flights["coinbase"].sequence
    assert first._flights["coinbase"].result_queue is second._flights["coinbase"].result_queue
    gate.set(); assert second.result_for("coinbase", broker) == 123.45


def test_recent_confirmed_observation_used_with_original_age(monkeypatch):
    _reset(); monkeypatch.setenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90")
    now_mono = time.monotonic(); now_epoch = time.time()
    cap._OBSERVATIONS["okx"] = cap._Observation(144.96, now_mono - 12.0, now_epoch - 12.0, 7)
    batch = object.__new__(cap._BalanceFetchBatch); value = batch._handle_failure("okx", "timeout")
    assert value == 144.96
    status = cap.current_refresh_fallback_status(); row = status["brokers"]["okx"]
    assert 10.0 <= row["age_s"] <= 20.0
    assert row["observed_epoch"] == now_epoch - 12.0
    assert status["source"] == "cached_live_observation"


def test_stale_observation_is_excluded_not_revived(monkeypatch):
    _reset(); monkeypatch.setenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "30")
    cap._OBSERVATIONS["kraken"] = cap._Observation(228.06, time.monotonic() - 120.0, time.time() - 120.0, 3)
    batch = object.__new__(cap._BalanceFetchBatch); value = batch._handle_failure("kraken", "timeout")
    assert value == 0.0
    status = cap.current_refresh_fallback_status()
    assert "kraken" in status["excluded_brokers"]
    assert status["all_recent"] is False
    assert status["source"] == "partial_or_excluded_fallback"


def test_v62_broker_specific_defaults_cover_observed_live_latency(monkeypatch):
    monkeypatch.delenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_COINBASE_FETCH_TIMEOUT_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_OKX_FETCH_TIMEOUT_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_KRAKEN_FETCH_TIMEOUT_S", raising=False)
    assert cap._broker_timeout_seconds("coinbase") >= 180.0
    assert cap._broker_timeout_seconds("okx") >= 75.0
    assert cap._broker_timeout_seconds("kraken") >= 75.0


def test_v62_cycle_deadline_cannot_undercut_slowest_broker(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_CYCLE_DEADLINE_S", "12")
    monkeypatch.delenv("NIJA_CAPITAL_COINBASE_FETCH_TIMEOUT_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_OKX_FETCH_TIMEOUT_S", raising=False)
    deadline = cap._cycle_deadline_seconds(("coinbase", "okx"))
    assert deadline >= cap._broker_timeout_seconds("coinbase") + 5.0


def test_v62_operator_can_raise_or_lower_dedicated_broker_timeout(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_COINBASE_FETCH_TIMEOUT_S", "210")
    monkeypatch.setenv("NIJA_CAPITAL_OKX_FETCH_TIMEOUT_S", "60")
    assert cap._broker_timeout_seconds("coinbase") == 210.0
    assert cap._broker_timeout_seconds("okx") == 60.0


def test_v62_unknown_broker_still_uses_generic_bound(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "9")
    assert cap._broker_timeout_seconds("alpaca") == 9.0


def test_overlapping_batches_both_receive_identical_success(monkeypatch):
    _reset()
    monkeypatch.setenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "2")
    gate = threading.Event()
    calls = []

    class Broker:
        def get_account_balance(self):
            calls.append(1)
            gate.wait(1.0)
            return 123.45

    broker = Broker()
    first = cap._BalanceFetchBatch({"kraken": broker})
    second = cap._BalanceFetchBatch({"kraken": broker})
    assert first._flights["kraken"] is second._flights["kraken"]
    gate.set()
    assert first.result_for("kraken", broker) == 123.45
    assert second.result_for("kraken", broker) == 123.45
    assert len(calls) == 1
    assert "kraken" in cap.current_refresh_fallback_status()["live_brokers"]


def test_overlapping_batches_both_receive_failure_without_false_success(monkeypatch):
    _reset()
    monkeypatch.setenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "2")
    gate = threading.Event()

    class Broker:
        def get_account_balance(self):
            gate.wait(1.0)
            raise RuntimeError("offline")

    broker = Broker()
    first = cap._BalanceFetchBatch({"kraken": broker})
    second = cap._BalanceFetchBatch({"kraken": broker})
    gate.set()
    assert first.result_for("kraken", broker) == 0.0
    assert second.result_for("kraken", broker) == 0.0
    assert "kraken" not in cap.current_refresh_fallback_status()["live_brokers"]
    assert "kraken" in cap.current_refresh_fallback_status()["excluded_brokers"]


def test_distinct_broker_instances_never_share_an_inflight_balance(monkeypatch):
    _reset()
    monkeypatch.setenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "2")
    gate = threading.Event()

    class Broker:
        def __init__(self, value):
            self.value = value
        def get_account_balance(self):
            gate.wait(1.0)
            return self.value

    old_broker, new_broker = Broker(1.0), Broker(2.0)
    old_batch = cap._BalanceFetchBatch({"kraken": old_broker})
    new_batch = cap._BalanceFetchBatch({"kraken": new_broker})
    assert old_batch._flights["kraken"] is not new_batch._flights["kraken"]
    gate.set()
    assert old_batch.result_for("kraken", old_broker) == 1.0
    assert new_batch.result_for("kraken", new_broker) == 2.0


def test_multibroker_flights_publish_only_to_their_own_result_holders(monkeypatch):
    """Catch late-bound loop closures when three workers finish after construction."""
    _reset()
    gate = threading.Event()

    class Broker:
        def __init__(self, amount):
            self.amount = amount

        def get_account_balance(self):
            assert gate.wait(2.0)
            return self.amount

    brokers = {
        "kraken": Broker(11.0),
        "okx": Broker(22.0),
        "coinbase": Broker(33.0),
    }
    batch = cap._BalanceFetchBatch(brokers)
    assert len({id(f.result_holder) for f in batch._flights.values()}) == 3
    assert len({id(f.result_event) for f in batch._flights.values()}) == 3
    gate.set()
    assert batch.result_for("kraken", brokers["kraken"]) == 11.0
    assert batch.result_for("okx", brokers["okx"]) == 22.0
    assert batch.result_for("coinbase", brokers["coinbase"]) == 33.0

    status = cap.current_refresh_fallback_status()
    assert status["used_fallback"] is False
    assert set(status["live_brokers"]) == set(brokers)


def test_multibroker_failure_does_not_release_or_overwrite_other_workers(monkeypatch):
    _reset()
    gate = threading.Event()

    class Broker:
        def __init__(self, amount=None):
            self.amount = amount

        def get_account_balance(self):
            assert gate.wait(2.0)
            if self.amount is None:
                raise RuntimeError("simulated_broker_failure")
            return self.amount

    brokers = {
        "kraken": Broker(11.0),
        "okx": Broker(None),
        "coinbase": Broker(33.0),
    }
    batch = cap._BalanceFetchBatch(brokers)
    gate.set()
    assert batch.result_for("kraken", brokers["kraken"]) == 11.0
    assert batch.result_for("okx", brokers["okx"]) == 0.0
    assert batch.result_for("coinbase", brokers["coinbase"]) == 33.0
    status = cap.current_refresh_fallback_status()
    assert set(status["live_brokers"]) == {"kraken", "coinbase"}
    assert "okx" in status["excluded_brokers"]
