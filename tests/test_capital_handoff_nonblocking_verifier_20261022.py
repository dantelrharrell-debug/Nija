"""Offline regressions for nonblocking capital->venue readiness handoff.

The capital coordinator may not make authenticated broker requests from CSM
ingestion.  A wakeup is only notification; it is never execution evidence.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _handoff():
    spec = importlib.util.spec_from_file_location(
        "nija_capital_handoff_nonblocking_test",
        ROOT / "bot" / "capital_readiness_handoff_v34.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(*, capital=758.61, brokers=3, stale=False):
    return SimpleNamespace(
        real_capital=capital, broker_count=brokers, is_stale=stale,
    )


def test_handoff_only_signals_verifier_and_preserves_canonical_proof(monkeypatch):
    handoff = _handoff()
    notified = threading.Event()

    def forbidden_broker_read(*_args, **_kwargs):
        raise AssertionError("capital coordinator must not call broker verifier")

    verifier = SimpleNamespace(
        request_reevaluation=notified.set,
        publish_once=forbidden_broker_read,
        evaluate_all=forbidden_broker_read,
    )
    monkeypatch.setitem(sys.modules, "three_venue_execution_readiness", verifier)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_THREE_VENUE_EXECUTION_READY", "0")
    handoff._publish_ready("bot.capital_csm_v2", _snapshot())

    assert notified.is_set()
    assert os.environ["NIJA_CAPITAL_HANDOFF_BROKER_COUNT"] == "3"
    assert os.environ["NIJA_CAPITAL_HANDOFF_REAL"] == "758.610000000000"
    assert float(os.environ["NIJA_CAPITAL_HANDOFF_ACCEPTED_TS"]) > 0
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] == "0"


def test_absent_verifier_does_not_import_broker_modules_or_grant_authority(monkeypatch, caplog):
    handoff = _handoff()
    monkeypatch.delitem(sys.modules, "three_venue_execution_readiness", raising=False)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    with caplog.at_level("INFO", logger="nija.capital_readiness_handoff_v34"):
        handoff._publish_ready("bot.capital_csm_v2", _snapshot())
    assert "reason=verifier_unavailable" in caplog.text
    assert "broker_io=false" in caplog.text
    assert "three_venue_execution_readiness" not in sys.modules
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"


def test_only_fresh_positive_accepted_snapshot_can_request_wake(monkeypatch):
    handoff = _handoff()
    requests = []
    monkeypatch.setitem(
        sys.modules, "three_venue_execution_readiness",
        SimpleNamespace(request_reevaluation=lambda: requests.append("wake")),
    )

    class FakeCSM:
        first_snap_accepted = True

        def ingest_snapshot(self, snapshot):
            return "READY"

    fake_module = ModuleType("nija_test_fake_capital_csm")
    fake_module.CapitalCSMv2 = FakeCSM
    assert handoff._patch(fake_module)
    csm = fake_module.CapitalCSMv2()
    csm.ingest_snapshot(_snapshot(stale=True))
    csm.ingest_snapshot(_snapshot(capital=0.0))
    csm.ingest_snapshot(_snapshot(brokers=0))
    assert requests == []
    csm.ingest_snapshot(_snapshot())
    assert requests == ["wake"]
    assert handoff._patch(fake_module)
    csm.ingest_snapshot(_snapshot())
    assert requests == ["wake", "wake"]


def test_wake_requests_coalesce_and_never_evaluate_brokers(monkeypatch):
    verifier = importlib.import_module("three_venue_execution_readiness")
    wake = threading.Event()
    monkeypatch.setattr(verifier, "_REEVALUATE_WAKE", wake)
    monkeypatch.setattr(
        verifier, "publish_once",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("request must not publish readiness")
        ),
    )
    monkeypatch.setattr(
        verifier, "evaluate_all",
        lambda: (_ for _ in ()).throw(
            AssertionError("request must not fetch brokerage data")
        ),
    )
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    verifier.request_reevaluation()
    verifier.request_reevaluation()
    assert wake.is_set()
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"


def test_existing_verifier_monitor_consumes_wake_without_new_workers(monkeypatch):
    verifier = importlib.import_module("three_venue_execution_readiness")

    class StopMonitor(BaseException):
        pass

    class ObserveWake:
        def __init__(self):
            self.cleared = 0
            self.waited = 0

        def clear(self):
            self.cleared += 1

        def wait(self, timeout):
            assert timeout >= 2.0
            self.waited += 1
            raise StopMonitor

    observer = ObserveWake()
    calls = []
    monkeypatch.setattr(verifier, "_REEVALUATE_WAKE", observer)
    monkeypatch.setattr(
        verifier, "reconcile_execution_readiness",
        lambda **kwargs: calls.append(kwargs),
    )
    with pytest.raises(StopMonitor):
        verifier._monitor()
    assert calls == [{"trigger": "monitor"}]
    assert observer.cleared == 1
    assert observer.waited == 1
