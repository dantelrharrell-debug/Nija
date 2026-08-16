from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import bot.platform_position_sync_v108_patch as v108


class BrokerType:
    def __init__(self, value: str):
        self.value = value


class FakeBroker:
    def __init__(self, *, connected: bool = True):
        self.connected = connected
        self._startup_position_sync_adopted = False
        self._startup_position_sync_fetch_ok = None
        self._startup_position_sync_error = None
        self.position_tracker = SimpleNamespace()


class FakeManager:
    def __init__(self, broker: FakeBroker):
        self.platform_brokers = {BrokerType("kraken"): broker}


def test_connected_unsynced_platform_broker_discovered_before_capital_ready():
    broker = FakeBroker(connected=True)
    manager = FakeManager(broker)
    assert v108._connected_unsynced_platform_brokers(manager) == [("kraken", broker)]


def test_synced_broker_is_not_redispatched():
    broker = FakeBroker(connected=True)
    broker._startup_position_sync_adopted = True
    manager = FakeManager(broker)
    assert v108._connected_unsynced_platform_brokers(manager) == []


def test_dispatch_is_single_flight_per_broker(monkeypatch):
    broker = FakeBroker(connected=True)
    manager = FakeManager(broker)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_worker(manager_arg, broker_name, broker_arg, key, trigger):
        calls.append((broker_name, trigger))
        entered.set()
        release.wait(timeout=1.0)
        with v108._LOCK:
            v108._ACTIVE.discard(key)

    monkeypatch.setattr(v108, "_worker", fake_worker)
    with v108._LOCK:
        v108._ACTIVE.clear()

    assert v108.dispatch_platform_position_sync(manager, trigger="first") == 1
    assert entered.wait(timeout=1.0)
    assert v108.dispatch_platform_position_sync(manager, trigger="second") == 0
    release.set()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with v108._LOCK:
            if not v108._ACTIVE:
                break
        time.sleep(0.01)

    assert calls == [("kraken", "first")]


def test_retry_policy_defaults_and_bounds(monkeypatch):
    monkeypatch.delenv("NIJA_PLATFORM_POSITION_SYNC_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("NIJA_PLATFORM_POSITION_SYNC_RETRY_BASE_S", raising=False)
    monkeypatch.delenv("NIJA_PLATFORM_POSITION_SYNC_RETRY_MAX_S", raising=False)
    assert v108._retry_policy() == (4, 1.0, 4.0)

    monkeypatch.setenv("NIJA_PLATFORM_POSITION_SYNC_MAX_ATTEMPTS", "999")
    monkeypatch.setenv("NIJA_PLATFORM_POSITION_SYNC_RETRY_BASE_S", "0")
    monkeypatch.setenv("NIJA_PLATFORM_POSITION_SYNC_RETRY_MAX_S", "0")
    assert v108._retry_policy() == (8, 0.1, 0.1)


def test_worker_retries_unsynced_fetch_and_recovers(monkeypatch):
    broker = FakeBroker(connected=True)
    manager = FakeManager(broker)
    key = (id(manager), id(broker))
    calls = []
    sleeps = []
    readiness = []

    class FakeSyncModule:
        @staticmethod
        def _get_entry_price_store():
            return None

        @staticmethod
        def _adopt_broker_positions(broker_arg, broker_name, eps):
            calls.append(broker_name)
            if len(calls) < 3:
                broker_arg._startup_position_sync_adopted = False
                broker_arg._startup_position_sync_fetch_ok = False
                broker_arg._startup_position_sync_error = "HTTPError:502"
                return 0
            broker_arg._startup_position_sync_adopted = True
            broker_arg._startup_position_sync_fetch_ok = True
            broker_arg._startup_position_sync_error = None
            return 0

    import bot
    monkeypatch.setattr(bot, "startup_position_sync", FakeSyncModule, raising=False)
    monkeypatch.setattr(v108, "_retry_policy", lambda: (4, 1.0, 4.0))
    monkeypatch.setattr(v108.time, "sleep", lambda delay: sleeps.append(delay))
    monkeypatch.setattr(v108, "_publish_readiness", lambda manager_arg, source: readiness.append(source))
    with v108._LOCK:
        v108._ACTIVE.add(key)

    v108._worker(manager, "coinbase", broker, key, "test")

    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_fetch_ok is True
    assert any(source.endswith("attempt_1") for source in readiness)
    assert any(source.endswith("attempt_2") for source in readiness)
    assert any(source.endswith("attempt_3") for source in readiness)
    assert readiness[-1].endswith(":final")
    with v108._LOCK:
        assert key not in v108._ACTIVE


def test_worker_preserves_fail_closed_state_on_error(monkeypatch):
    broker = FakeBroker(connected=True)
    manager = FakeManager(broker)
    key = (id(manager), id(broker))

    class FakeSyncModule:
        @staticmethod
        def _get_entry_price_store():
            return None

        @staticmethod
        def _adopt_broker_positions(*args, **kwargs):
            raise TimeoutError("position snapshot timed out")

    import bot
    monkeypatch.setattr(bot, "startup_position_sync", FakeSyncModule, raising=False)
    monkeypatch.setattr(v108, "_retry_policy", lambda: (1, 0.1, 0.1))
    monkeypatch.setattr(v108, "_publish_readiness", lambda *args, **kwargs: None)
    with v108._LOCK:
        v108._ACTIVE.add(key)

    v108._worker(manager, "kraken", broker, key, "test")

    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert "TimeoutError" in str(broker._startup_position_sync_error)
    with v108._LOCK:
        assert key not in v108._ACTIVE


def test_worker_exhausts_retries_without_granting_readiness(monkeypatch):
    broker = FakeBroker(connected=True)
    manager = FakeManager(broker)
    key = (id(manager), id(broker))
    calls = []

    class FakeSyncModule:
        @staticmethod
        def _get_entry_price_store():
            return None

        @staticmethod
        def _adopt_broker_positions(broker_arg, broker_name, eps):
            calls.append(broker_name)
            broker_arg._startup_position_sync_adopted = False
            broker_arg._startup_position_sync_fetch_ok = False
            broker_arg._startup_position_sync_error = "HTTPError:502 Bad Gateway"
            return 0

    import bot
    monkeypatch.setattr(bot, "startup_position_sync", FakeSyncModule, raising=False)
    monkeypatch.setattr(v108, "_retry_policy", lambda: (3, 0.1, 0.1))
    monkeypatch.setattr(v108.time, "sleep", lambda delay: None)
    monkeypatch.setattr(v108, "_publish_readiness", lambda *args, **kwargs: None)
    with v108._LOCK:
        v108._ACTIVE.add(key)

    v108._worker(manager, "coinbase", broker, key, "test")

    assert calls == ["platform:coinbase"] * 3
    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert "502" in str(broker._startup_position_sync_error)
    with v108._LOCK:
        assert key not in v108._ACTIVE


def test_patch_dispatches_before_original_capital_refresh(monkeypatch):
    order = []

    class Manager:
        def refresh_capital_authority(self, trigger="manual"):
            order.append(("refresh", trigger))
            return {"ready": False, "total_capital": 0.0}

    module = SimpleNamespace(__name__="bot.multi_account_broker_manager", MultiAccountBrokerManager=Manager)
    monkeypatch.setattr(
        v108,
        "dispatch_platform_position_sync",
        lambda manager, trigger: order.append(("dispatch", trigger)) or 1,
    )

    assert v108._patch_mabm(module) is True
    result = Manager().refresh_capital_authority(trigger="bootstrap_contract:1")

    assert result == {"ready": False, "total_capital": 0.0}
    assert order == [
        ("dispatch", "bootstrap_contract:1"),
        ("refresh", "bootstrap_contract:1"),
    ]
