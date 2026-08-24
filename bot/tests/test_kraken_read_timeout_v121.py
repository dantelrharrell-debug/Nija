from __future__ import annotations

import types

import pytest

from bot import kraken_read_timeout_v121_patch as v121


class FakeAPI:
    def __init__(self):
        self.private_calls = []
        self.public_calls = []

    def query_private(self, method, data=None, timeout=None):
        self.private_calls.append((method, data, timeout))
        return {"error": [], "result": {}}

    def query_public(self, method, data=None, timeout=None):
        self.public_calls.append((method, data, timeout))
        return {"error": [], "result": {}}


class BusyLock:
    def __init__(self):
        self.acquire_calls = []
        self.release_calls = 0

    def acquire(self, *args, **kwargs):
        self.acquire_calls.append((args, kwargs))
        return False

    def release(self):
        self.release_calls += 1


class ReentrantLock:
    def __init__(self):
        self.depth = 0
        self.acquire_calls = []
        self.release_calls = 0

    def acquire(self, *args, **kwargs):
        self.acquire_calls.append((args, kwargs))
        self.depth += 1
        return True

    def release(self):
        self.release_calls += 1
        self.depth -= 1



def test_read_only_private_call_gets_bounded_timeout(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_PRIVATE_READ_TIMEOUT_S", "7")
    api = FakeAPI()
    assert v121._wrap_api(api) is True

    api.query_private("Balance", {})
    assert api.private_calls[-1] == ("Balance", {}, 7.0)


def test_mutating_private_call_preserves_existing_timeout_semantics(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_PRIVATE_READ_TIMEOUT_S", "7")
    api = FakeAPI()
    assert v121._wrap_api(api) is True

    api.query_private("AddOrder", {"pair": "XBTUSD"})
    assert api.private_calls[-1] == ("AddOrder", {"pair": "XBTUSD"}, None)


def test_explicit_private_timeout_is_preserved(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_PRIVATE_READ_TIMEOUT_S", "7")
    api = FakeAPI()
    assert v121._wrap_api(api) is True

    api.query_private("Balance", {}, timeout=3)
    assert api.private_calls[-1] == ("Balance", {}, 3)


def test_public_call_gets_bounded_timeout(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_PUBLIC_READ_TIMEOUT_S", "5")
    api = FakeAPI()
    assert v121._wrap_api(api) is True

    api.query_public("Ticker", {"pair": "XBTUSD"})
    assert api.public_calls[-1] == ("Ticker", {"pair": "XBTUSD"}, 5.0)


def test_broker_manager_patch_wraps_live_api_without_fabricating_positions():
    api = FakeAPI()
    lock = ReentrantLock()

    class KrakenBroker:
        @classmethod
        def _iter_live(cls):
            return []

        def _kraken_private_call(self, method, params=None, category=None):
            return self.api.query_private(method, params)

    fake_module = types.ModuleType("bot.broker_manager")
    fake_module.KrakenBroker = KrakenBroker
    fake_module.get_kraken_api_lock = lambda: lock

    assert v121._patch_broker_manager(fake_module) is True
    broker = KrakenBroker()
    broker.api = api
    result = broker._kraken_private_call("Balance")

    assert result == {"error": [], "result": {}}
    assert api.private_calls[-1][2] == v121._private_read_timeout_s()
    assert lock.acquire_calls
    assert lock.release_calls == 1
    assert lock.depth == 0


def test_read_only_private_call_fails_closed_when_global_lock_is_busy(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_PRIVATE_READ_LOCK_WAIT_S", "2")
    lock = BusyLock()

    class KrakenBroker:
        @classmethod
        def _iter_live(cls):
            return []

        def _kraken_private_call(self, method, params=None, category=None):
            raise AssertionError("busy read must not enter original broker call")

    fake_module = types.ModuleType("bot.broker_manager")
    fake_module.KrakenBroker = KrakenBroker
    fake_module.get_kraken_api_lock = lambda: lock

    assert v121._patch_broker_manager(fake_module) is True
    broker = KrakenBroker()
    broker.api = FakeAPI()

    with pytest.raises(v121.KrakenReadLockBusy, match="Kraken read lock busy"):
        broker._kraken_private_call("Balance")

    assert lock.acquire_calls
    assert lock.release_calls == 0


def test_mutating_private_call_does_not_use_bounded_read_lock():
    lock = BusyLock()
    calls = []

    class KrakenBroker:
        @classmethod
        def _iter_live(cls):
            return []

        def _kraken_private_call(self, method, params=None, category=None):
            calls.append((method, params, category))
            return {"ok": True}

    fake_module = types.ModuleType("bot.broker_manager")
    fake_module.KrakenBroker = KrakenBroker
    fake_module.get_kraken_api_lock = lambda: lock

    assert v121._patch_broker_manager(fake_module) is True
    broker = KrakenBroker()
    broker.api = FakeAPI()

    assert broker._kraken_private_call("AddOrder", {"pair": "XBTUSD"}) == {"ok": True}
    assert calls == [("AddOrder", {"pair": "XBTUSD"}, None)]
    assert lock.acquire_calls == []
    assert lock.release_calls == 0
