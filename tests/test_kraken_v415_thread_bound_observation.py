"""Regression: one Kraken Balance observation must belong to its own call.

v415 is a non-authorizing capital freshness bridge. In particular, a
concurrent cached response cannot inherit another worker's authenticated
Balance event on the same broker object.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest


_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "bot"
    / "runtime_kraken_platform_balance_capital_feed_v415_patch.py"
)


def _install_isolated(monkeypatch, broker_class):
    spec = importlib.util.spec_from_file_location(
        "nija_v415_thread_bound_test", _SOURCE
    )
    assert spec and spec.loader
    v415 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v415)

    recorded = []
    broker_module = ModuleType("bot.broker_manager")
    broker_module.KrakenBroker = broker_class
    capital_module = ModuleType("bot.capital_authority")
    capital_module.get_capital_authority = lambda: SimpleNamespace(
        feed_broker_balance=lambda broker, balance, timestamp: recorded.append(
            (broker, balance, timestamp)
        )
    )
    monkeypatch.setitem(sys.modules, "bot.broker_manager", broker_module)
    monkeypatch.setitem(sys.modules, "bot.capital_authority", capital_module)
    # This suite tests attribution, not authentication: the actual verifier
    # remains mandatory and unchanged in production.
    monkeypatch.setattr(
        v415, "_valid_credential_balance",
        lambda broker, response: (
            isinstance(response, dict)
            and isinstance(response.get("result"), dict)
        ),
    )
    assert v415._patch_kraken_class() is True
    return recorded


def test_concurrent_cached_read_cannot_borrow_other_threads_balance(monkeypatch):
    observed = threading.Event()
    release = threading.Event()
    errors = []

    class Broker:
        account_identifier = "PLATFORM"

        def _kraken_private_call(self, method):
            assert method == "Balance"
            return {"result": {"ZUSD": "100"}}

        def get_account_balance(self):
            if threading.current_thread().name == "v415-authenticated-read":
                self._kraken_private_call("Balance")
                observed.set()
                assert release.wait(5), "test release did not arrive"
                return 100.0
            # Existing broker balance cache: no private broker call.
            return 90.0

    feeds = _install_isolated(monkeypatch, Broker)
    broker = Broker()

    def authenticated_read():
        try:
            assert broker.get_account_balance() == 100.0
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(
        target=authenticated_read, name="v415-authenticated-read", daemon=True
    )
    worker.start()
    try:
        assert observed.wait(5)
        # Another thread has a real authenticated observation in progress.
        # A cached return here is NOT new broker evidence.
        assert broker.get_account_balance() == 90.0
        assert feeds == []
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert not errors
    assert len(feeds) == 1
    assert feeds[0][:2] == ("kraken", 100.0)
    assert isinstance(feeds[0][2], datetime)
    assert broker.get_account_balance() == 90.0
    assert len(feeds) == 1


def test_failed_balance_call_does_not_leak_observation_to_next_call(monkeypatch):
    class Broker:
        account_identifier = "PLATFORM"

        def __init__(self):
            self.first = True

        def _kraken_private_call(self, method):
            return {"result": {"ZUSD": "25"}}

        def get_account_balance(self):
            if self.first:
                self.first = False
                self._kraken_private_call("Balance")
                raise RuntimeError("local valuation failed")
            return 25.0  # cached, no authenticated read

    feeds = _install_isolated(monkeypatch, Broker)
    broker = Broker()
    with pytest.raises(RuntimeError, match="valuation failed"):
        broker.get_account_balance()
    assert feeds == []
    assert broker.get_account_balance() == 25.0
    assert feeds == []


def test_same_call_authenticated_balance_still_feeds_once(monkeypatch):
    class Broker:
        account_identifier = "PLATFORM"

        def _kraken_private_call(self, method):
            assert method == "Balance"
            return {"result": {"ZUSD": "125"}}

        def get_account_balance(self):
            self._kraken_private_call("Balance")
            return 125.0

    feeds = _install_isolated(monkeypatch, Broker)
    assert Broker().get_account_balance() == 125.0
    assert len(feeds) == 1
    assert feeds[0][:2] == ("kraken", 125.0)
    assert isinstance(feeds[0][2], datetime)
