from __future__ import annotations

import importlib
import sys
import threading
import types


def _patch():
    return importlib.import_module("bot.runtime_position_protection_liveness_v348_patch")


def test_candidate_union_adds_v285_stale_candidate(monkeypatch):
    patch = _patch()
    broker = object()
    fake_v285 = types.ModuleType("bot.runtime_authoritative_position_coverage_v285_patch")
    fake_v285._platform_candidates = lambda manager: [("kraken", broker)]
    monkeypatch.setitem(sys.modules, fake_v285.__name__, fake_v285)

    result = patch._candidate_union(object(), [])
    assert result == [("kraken", broker)]


def test_candidate_union_deduplicates_existing_candidate(monkeypatch):
    patch = _patch()
    broker = object()
    fake_v285 = types.ModuleType("bot.runtime_authoritative_position_coverage_v285_patch")
    fake_v285._platform_candidates = lambda manager: [("kraken", broker)]
    monkeypatch.setitem(sys.modules, fake_v285.__name__, fake_v285)

    result = patch._candidate_union(object(), [("kraken", broker)])
    assert result == [("kraken", broker)]


def test_dispatch_uses_existing_v108_worker_without_granting_readiness(monkeypatch):
    patch = _patch()
    manager = object()
    broker = object()
    active = set()
    lock = threading.RLock()
    calls = []

    fake_v161 = types.ModuleType("bot.runtime_capital_position_convergence_v161_patch")
    fake_v161._canonical_manager = lambda: manager

    fake_v108 = types.ModuleType("bot.platform_position_sync_v108_patch")
    fake_v108._ACTIVE = active
    fake_v108._LOCK = lock
    fake_v108._connected_unsynced_platform_brokers = lambda m: [("coinbase", broker)]

    def worker(m, name, b, key, trigger):
        calls.append((m, name, b, key, trigger))
        with lock:
            active.discard(key)

    fake_v108._worker = worker
    monkeypatch.setitem(sys.modules, fake_v161.__name__, fake_v161)
    monkeypatch.setitem(sys.modules, fake_v108.__name__, fake_v108)

    started = patch._dispatch_authoritative_workers()
    assert started == 1

    # The worker thread is asynchronous; join by polling briefly rather than
    # asserting scheduling order.
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.01)
    assert calls
    assert calls[0][0] is manager
    assert calls[0][1] == "coinbase"
    assert calls[0][2] is broker
    assert calls[0][4] == "v348_stale_snapshot_recovery"


def test_no_execution_or_position_readiness_is_written_by_v348():
    patch = _patch()
    source = open(patch.__file__, "r", encoding="utf-8").read()
    assert "mark_ready(\"position_sync_ready\")" not in source
    assert "mark_ready(\"execution_ready\")" not in source
    assert "forced_trade=false" in source
    assert "stale_promoted=false" in source
