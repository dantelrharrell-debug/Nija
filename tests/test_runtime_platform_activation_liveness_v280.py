from __future__ import annotations

from types import SimpleNamespace

import bot.runtime_platform_activation_liveness_v280_patch as v280


class _Broker:
    def __init__(self, *, connected: bool = False, credentials: bool = True, connect_result: bool = True):
        self.connected = connected
        self.credentials_configured = credentials
        self.account_type = "platform"
        self._connect_result = connect_result
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self._connect_result:
            self.connected = True
        return self._connect_result


class _Manager:
    def __init__(self):
        self._platform_brokers = {}
        self._registry_meta_lock = v280.threading.RLock()
        self.sync_calls = []
        self.refresh_registry_calls = 0

    def refresh_registry(self):
        self.refresh_registry_calls += 1

    def _sync_reconnect_readiness(self, key, broker):
        self.sync_calls.append((key, broker))


def test_v280_adopts_only_existing_process_platform_candidate(monkeypatch):
    broker = _Broker(connected=True)
    manager = _Manager()
    key = SimpleNamespace(value="coinbase")
    monkeypatch.setattr(v280, "_platform_key", lambda manager, venue: key)

    assert v280._adopt_existing(manager, "coinbase", broker) is True
    assert manager._platform_brokers[key] is broker
    assert manager.refresh_registry_calls == 1


def test_v280_refuses_conflicting_manager_identity(monkeypatch):
    existing = _Broker(connected=True)
    candidate = _Broker(connected=True)
    manager = _Manager()
    key = SimpleNamespace(value="coinbase")
    manager._platform_brokers[key] = existing

    assert v280._adopt_existing(manager, "coinbase", candidate) is False
    assert manager._platform_brokers[key] is existing


def test_v280_never_connects_without_real_credentials(monkeypatch):
    broker = _Broker(connected=False, credentials=False)
    manager = _Manager()
    key = SimpleNamespace(value="coinbase")
    manager._platform_brokers[key] = broker
    monkeypatch.setattr(v280, "_configured_by_policy", lambda venue, broker: True)

    assert v280._connect_existing(manager, "coinbase", broker) is False
    assert broker.connect_calls == 0
    assert manager.sync_calls == []


def test_v280_requires_connect_return_and_connected_state(monkeypatch):
    broker = _Broker(connected=False, credentials=True, connect_result=False)
    manager = _Manager()
    key = SimpleNamespace(value="coinbase")
    manager._platform_brokers[key] = broker
    monkeypatch.setattr(v280, "_configured_by_policy", lambda venue, broker: True)

    assert v280._connect_existing(manager, "coinbase", broker) is False
    assert broker.connect_calls == 1
    assert manager.sync_calls == []


def test_v280_syncs_only_after_real_connection(monkeypatch):
    broker = _Broker(connected=False, credentials=True, connect_result=True)
    manager = _Manager()
    key = SimpleNamespace(value="coinbase")
    manager._platform_brokers[key] = broker
    monkeypatch.setattr(v280, "_configured_by_policy", lambda venue, broker: True)

    assert v280._connect_existing(manager, "coinbase", broker) is True
    assert broker.connect_calls == 1
    assert manager.sync_calls == [(key, broker)]


def test_v280_v182_reassert_wakes_authoritative_position_sync(monkeypatch):
    calls = []
    manager = object()

    def original_install():
        calls.append("install")
        return True

    fake_v182 = SimpleNamespace(install=original_install, install_import_hook=original_install)
    real_import = v280.importlib.import_module

    def fake_import(name):
        if name == "bot.runtime_position_fetch_proof_v182_patch":
            return fake_v182
        return real_import(name)

    monkeypatch.setattr(v280.importlib, "import_module", fake_import)
    monkeypatch.setattr(v280, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v280, "_wake_position_sync", lambda mgr, trigger: calls.append((mgr, trigger)) or 1)

    assert v280._patch_v182_install() is True
    assert fake_v182.install() is True
    assert calls == ["install", (manager, "v280_v182_reassert")]


def test_v280_no_candidate_never_fabricates_broker(monkeypatch):
    manager = _Manager()
    monkeypatch.setattr(v280, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v280, "_global_candidate", lambda venue: None)
    monkeypatch.setattr(v280, "_wake_position_sync", lambda manager, trigger: 0)
    monkeypatch.setattr(v280, "_request_capital_refresh", lambda manager, trigger: None)

    outcomes = v280.reconcile_once()
    assert outcomes == {
        "coinbase": "no_existing_platform_object",
        "okx": "no_existing_platform_object",
    }
    assert manager._platform_brokers == {}
