from __future__ import annotations

import os
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest


os.environ.setdefault("NIJA_SKIP_BOT_PACKAGE_INIT", "1")
os.environ.setdefault("NIJA_TESTING", "1")
os.environ.setdefault("NIJA_UNIT_TESTING", "1")
os.environ.setdefault("NIJA_NO_NETWORK", "1")


def test_v314_promotes_existing_balance_owner_token_without_new_call(monkeypatch):
    from bot import runtime_kraken_credential_read_convergence_v299_patch as v299

    gate = SimpleNamespace(
        _condition=threading.Condition(threading.Lock()),
        _waiters=[{"priority": 10, "sequence": 4, "thread_id": 12345}],
        _held=False,
        _owner=None,
    )
    broker = SimpleNamespace(account_identifier="PLATFORM")
    flight = {"owner_thread": 12345}

    monkeypatch.setattr(v299, "_caller_is_authoritative", lambda: True)
    monkeypatch.setattr(v299, "_shared_monitoring_gate", lambda _broker: gate)
    with v299._FLIGHT_LOCK:
        v299._PROMOTED_OWNER_THREADS.clear()

    promoted = v299._promote_existing_balance_owner(broker, flight, "cred:test")

    assert promoted is True
    assert gate._waiters[0]["priority"] == 0
    with v299._FLIGHT_LOCK:
        assert 12345 in v299._PROMOTED_OWNER_THREADS
        v299._PROMOTED_OWNER_THREADS.clear()


def test_v314_priority_bridge_upgrades_only_named_owner_thread(monkeypatch):
    from bot import runtime_kraken_credential_read_convergence_v299_patch as v299

    fake_v297 = SimpleNamespace(_authoritative_priority=lambda: False)
    monkeypatch.setattr(v299, "_v297", lambda: fake_v297)
    with v299._FLIGHT_LOCK:
        v299._PROMOTED_OWNER_THREADS.clear()
        v299._PROMOTED_OWNER_THREADS.add(threading.get_ident())

    assert v299._ensure_priority_bridge() is True
    assert fake_v297._authoritative_priority() is True

    with v299._FLIGHT_LOCK:
        v299._PROMOTED_OWNER_THREADS.clear()
    assert fake_v297._authoritative_priority() is False


def test_v314_non_authoritative_join_does_not_promote(monkeypatch):
    from bot import runtime_kraken_credential_read_convergence_v299_patch as v299

    gate = SimpleNamespace(
        _condition=threading.Condition(threading.Lock()),
        _waiters=[{"priority": 10, "sequence": 1, "thread_id": 9001}],
        _held=False,
        _owner=None,
    )
    monkeypatch.setattr(v299, "_caller_is_authoritative", lambda: False)
    monkeypatch.setattr(v299, "_shared_monitoring_gate", lambda _broker: gate)
    with v299._FLIGHT_LOCK:
        v299._PROMOTED_OWNER_THREADS.clear()

    assert v299._promote_existing_balance_owner(
        SimpleNamespace(account_identifier="PLATFORM"),
        {"owner_thread": 9001},
        "cred:test",
    ) is False
    assert gate._waiters[0]["priority"] == 10
    with v299._FLIGHT_LOCK:
        assert not v299._PROMOTED_OWNER_THREADS


def test_v315_publishes_exact_authoritative_list_to_loaded_v285(monkeypatch):
    from bot import position_sync_failure_truth_v98_patch as v98

    captured = []
    fake_v285 = ModuleType("bot.runtime_authoritative_position_coverage_v285_patch")

    def record(broker, positions):
        captured.append((broker, positions))
        return True

    fake_v285._record_snapshot_success = record
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_authoritative_position_coverage_v285_patch",
        fake_v285,
    )

    authoritative = [
        {"symbol": "BTC-USD", "quantity": 0.5, "entry_price": 100.0},
        {"symbol": "ETH-USD", "quantity": 1.25, "entry_price": 50.0},
    ]

    class Broker:
        account_identifier = "PLATFORM"

        def get_positions(self):
            return authoritative

    broker = Broker()
    proxy = v98._FetchProofProxy(broker)
    result = proxy.get_positions()

    assert result is authoritative
    assert proxy.fetch_ok is True
    assert proxy.fetch_error is None
    assert len(captured) == 1
    assert captured[0][0] is broker
    assert captured[0][1] == authoritative


def test_v315_loaded_v285_rejection_fails_closed(monkeypatch):
    from bot import position_sync_failure_truth_v98_patch as v98

    fake_v285 = ModuleType("bot.runtime_authoritative_position_coverage_v285_patch")
    fake_v285._record_snapshot_success = lambda _broker, _positions: False
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_authoritative_position_coverage_v285_patch",
        fake_v285,
    )

    class Broker:
        account_identifier = "PLATFORM"

        def get_positions(self):
            return [{"symbol": "BTC-USD", "quantity": 1.0}]

    proxy = v98._FetchProofProxy(Broker())
    with pytest.raises(RuntimeError, match="snapshot publication rejected"):
        proxy.get_positions()

    assert proxy.fetch_ok is False
    assert proxy.fetch_error == "v285_snapshot_publish_rejected"


def test_v315_does_not_import_or_fabricate_v285_when_not_loaded(monkeypatch):
    from bot import position_sync_failure_truth_v98_patch as v98

    monkeypatch.delitem(
        sys.modules,
        "bot.runtime_authoritative_position_coverage_v285_patch",
        raising=False,
    )
    monkeypatch.delitem(
        sys.modules,
        "runtime_authoritative_position_coverage_v285_patch",
        raising=False,
    )

    class Broker:
        account_identifier = "PLATFORM"

        def get_positions(self):
            return []

    proxy = v98._FetchProofProxy(Broker())
    assert proxy.get_positions() == []
    assert proxy.fetch_ok is True
    assert "bot.runtime_authoritative_position_coverage_v285_patch" not in sys.modules
