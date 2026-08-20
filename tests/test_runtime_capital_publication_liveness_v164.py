from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import bot.runtime_capital_publication_liveness_v164_patch as v164


@dataclass
class Snapshot:
    real_capital: float
    broker_balances: dict[str, float]
    broker_count: int
    expected_brokers: int


def test_complete_positive_snapshot_requires_all_expected_positive_brokers():
    complete = Snapshot(300.0, {"kraken": 200.0, "coinbase": 100.0}, 2, 2)
    partial = Snapshot(100.0, {"coinbase": 100.0}, 1, 2)
    zero_member = Snapshot(100.0, {"coinbase": 100.0, "kraken": 0.0}, 2, 2)

    assert v164._snapshot_complete_positive(complete) is True
    assert v164._snapshot_complete_positive(partial) is False
    assert v164._snapshot_complete_positive(zero_member) is False
    assert v164._snapshot_partial(partial) is True
    assert v164._snapshot_partial(complete) is False


def test_canonical_platform_instance_uses_mabm_registry(monkeypatch):
    kraken = SimpleNamespace(connected=True, broker_name="kraken")
    manager = SimpleNamespace(platform_brokers={"kraken": kraken})
    monkeypatch.setattr(v164, "_canonical_manager", lambda: manager)

    assert v164._canonical_platform_instance("kraken") is kraken


def test_canonical_platform_instance_rejects_disconnected_broker(monkeypatch):
    kraken = SimpleNamespace(connected=False, broker_name="kraken")
    manager = SimpleNamespace(platform_brokers={"kraken": kraken})
    monkeypatch.setattr(v164, "_canonical_manager", lambda: manager)

    assert v164._canonical_platform_instance("kraken") is None


def test_current_complete_fresh_requires_accepted_nonstale_status():
    complete = Snapshot(300.0, {"kraken": 200.0, "coinbase": 100.0}, 2, 2)

    class Authority:
        def __init__(self, accepted: bool, stale: bool):
            self._status = SimpleNamespace(accepted=accepted, stale=stale)

        def get_snapshot_publication_status(self):
            return self._status

        def get_typed_snapshot(self):
            return complete

    assert v164._current_complete_fresh(Authority(True, False)) is complete
    assert v164._current_complete_fresh(Authority(False, False)) is None
    assert v164._current_complete_fresh(Authority(True, True)) is None


def test_runtime_refresh_thread_cap_is_bounded(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_MAX_RUNTIME_REFRESH_THREADS", "20")
    assert v164._max_runtime_refresh_threads() == 4
    monkeypatch.setenv("NIJA_CAPITAL_MAX_RUNTIME_REFRESH_THREADS", "0")
    assert v164._max_runtime_refresh_threads() == 1


def test_rollover_cap_counts_only_live_v142_runtime_workers(monkeypatch):
    class FakeThread:
        def __init__(self, name: str, alive: bool):
            self.name = name
            self._alive = alive

        def is_alive(self):
            return self._alive

    monkeypatch.setattr(
        v164.threading,
        "enumerate",
        lambda: [
            FakeThread("capital-runtime-refresh-v142-g1", True),
            FakeThread("capital-runtime-refresh-v142-g2", False),
            FakeThread("TradingLoop", True),
        ],
    )
    monkeypatch.setenv("NIJA_CAPITAL_MAX_RUNTIME_REFRESH_THREADS", "1")

    capped, live, maximum = v164._rollover_thread_cap_reached()
    assert capped is True
    assert live == 1
    assert maximum == 1
