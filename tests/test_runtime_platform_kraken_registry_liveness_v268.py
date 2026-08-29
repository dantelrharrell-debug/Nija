from __future__ import annotations

import os
import threading
from enum import Enum
from types import SimpleNamespace

from bot import runtime_platform_kraken_registry_liveness_v268_patch as v268


class _AccountType(Enum):
    PLATFORM = "platform"
    USER = "user"


class _BrokerType(Enum):
    KRAKEN = "kraken"


class _Kraken:
    def __init__(self, *, connected: bool, account_type: _AccountType = _AccountType.PLATFORM) -> None:
        self.connected = connected
        self.account_type = account_type
        self.broker_type = _BrokerType.KRAKEN
        self._hard_stopped = False


class _KrakenClass:
    live = []

    @classmethod
    def _iter_live(cls):
        return list(cls.live)


class _BrokerModule:
    _PLATFORM_BROKER_REGISTRY_LOCK = threading.RLock()
    _PLATFORM_BROKER_INSTANCES = {}
    GLOBAL_PLATFORM_BROKERS = {}
    _PLATFORM_BROKER_CONNECTED = {}
    KrakenBroker = _KrakenClass
    BrokerType = _BrokerType


class _Manager:
    def __init__(self, broker=...) -> None:
        self._platform_brokers = {}
        if broker is not ...:
            self._platform_brokers[_BrokerType.KRAKEN] = broker
        self._platform_connected = {}
        self._registry_meta_lock = threading.RLock()
        self.sync_calls = []

    def _sync_reconnect_readiness(self, broker_type, broker) -> None:
        self.sync_calls.append((broker_type, broker))


def _reset_broker_module() -> None:
    _BrokerModule._PLATFORM_BROKER_INSTANCES = {}
    _BrokerModule.GLOBAL_PLATFORM_BROKERS = {}
    _BrokerModule._PLATFORM_BROKER_CONNECTED = {}
    _KrakenClass.live = []


def test_registry_presence_is_not_connection_truth() -> None:
    _reset_broker_module()
    broker = _Kraken(connected=False)
    manager = _Manager(broker)

    v268._write_registry_truth(manager, _BrokerModule, _BrokerType.KRAKEN, broker)

    assert _BrokerModule._PLATFORM_BROKER_INSTANCES["kraken"] is broker
    assert _BrokerModule.GLOBAL_PLATFORM_BROKERS["kraken"] is True
    assert _BrokerModule._PLATFORM_BROKER_CONNECTED["kraken"] is False
    assert manager._platform_connected["kraken"] is False


def test_unique_connected_platform_kraken_replaces_disconnected_manager_copy(monkeypatch) -> None:
    _reset_broker_module()
    disconnected = _Kraken(connected=False)
    connected = _Kraken(connected=True)
    manager = _Manager(disconnected)
    _BrokerModule._PLATFORM_BROKER_INSTANCES["kraken"] = connected
    _KrakenClass.live = [disconnected, connected]
    monkeypatch.setattr(v268, "_wake_position_sync", lambda _manager: True)

    assert v268._repair_manager_registry(manager, _BrokerModule) is True
    assert manager._platform_brokers[_BrokerType.KRAKEN] is connected
    assert manager.sync_calls == [(_BrokerType.KRAKEN, connected)]
    assert _BrokerModule.GLOBAL_PLATFORM_BROKERS["kraken"] is True
    assert _BrokerModule._PLATFORM_BROKER_CONNECTED["kraken"] is True


def test_missing_manager_kraken_entry_is_repaired_from_unique_connected_platform_candidate(monkeypatch) -> None:
    _reset_broker_module()
    connected = _Kraken(connected=True)
    manager = _Manager()
    _BrokerModule._PLATFORM_BROKER_INSTANCES["kraken"] = connected
    _KrakenClass.live = [connected]
    wakes = []
    monkeypatch.setattr(v268, "_wake_position_sync", lambda target: wakes.append(target) or True)

    assert v268._repair_manager_registry(manager, _BrokerModule) is True
    assert manager._platform_brokers[_BrokerType.KRAKEN] is connected
    assert manager.sync_calls == [(_BrokerType.KRAKEN, connected)]
    assert wakes == [manager]
    assert _BrokerModule.GLOBAL_PLATFORM_BROKERS["kraken"] is True
    assert _BrokerModule._PLATFORM_BROKER_CONNECTED["kraken"] is True


def test_missing_manager_entry_with_no_connected_platform_candidate_is_not_fabricated() -> None:
    _reset_broker_module()
    manager = _Manager()

    assert v268._repair_manager_registry(manager, _BrokerModule) is True
    assert manager._platform_brokers == {}
    assert manager.sync_calls == []


def test_missing_manager_entry_with_multiple_connected_platform_candidates_fails_closed() -> None:
    _reset_broker_module()
    first = _Kraken(connected=True)
    second = _Kraken(connected=True)
    manager = _Manager()
    _BrokerModule._PLATFORM_BROKER_INSTANCES["kraken"] = first
    _KrakenClass.live = [first, second]

    assert v268._repair_manager_registry(manager, _BrokerModule) is False
    assert manager._platform_brokers == {}
    assert manager.sync_calls == []


def test_multiple_connected_platform_kraken_candidates_fail_closed_without_mutation() -> None:
    _reset_broker_module()
    disconnected = _Kraken(connected=False)
    first = _Kraken(connected=True)
    second = _Kraken(connected=True)
    manager = _Manager(disconnected)
    _BrokerModule._PLATFORM_BROKER_INSTANCES["kraken"] = first
    _KrakenClass.live = [first, second]

    assert v268._repair_manager_registry(manager, _BrokerModule) is False
    assert manager._platform_brokers[_BrokerType.KRAKEN] is disconnected
    assert manager.sync_calls == []


def test_user_kraken_never_satisfies_platform_repair() -> None:
    _reset_broker_module()
    disconnected = _Kraken(connected=False)
    user = _Kraken(connected=True, account_type=_AccountType.USER)
    manager = _Manager(disconnected)
    _KrakenClass.live = [user]

    assert v268._repair_manager_registry(manager, _BrokerModule) is True
    assert manager._platform_brokers[_BrokerType.KRAKEN] is disconnected
    assert manager.sync_calls == []
    assert _BrokerModule._PLATFORM_BROKER_CONNECTED["kraken"] is False


def test_user_kraken_never_populates_missing_platform_manager_entry() -> None:
    _reset_broker_module()
    user = _Kraken(connected=True, account_type=_AccountType.USER)
    manager = _Manager()
    _KrakenClass.live = [user]

    assert v268._repair_manager_registry(manager, _BrokerModule) is True
    assert manager._platform_brokers == {}
    assert manager.sync_calls == []


def test_disconnected_state_is_not_promoted_without_live_connected_candidate() -> None:
    _reset_broker_module()
    disconnected = _Kraken(connected=False)
    manager = _Manager(disconnected)

    assert v268._repair_manager_registry(manager, _BrokerModule) is True
    assert manager._platform_brokers[_BrokerType.KRAKEN] is disconnected
    assert _BrokerModule.GLOBAL_PLATFORM_BROKERS["kraken"] is True
    assert _BrokerModule._PLATFORM_BROKER_CONNECTED["kraken"] is False


def test_nonce_topology_probe_repairs_before_classifying_kraken_inactive(monkeypatch) -> None:
    manager = SimpleNamespace()
    calls = []

    monkeypatch.setattr(v268, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v268, "_broker_module", lambda: _BrokerModule)
    monkeypatch.setattr(v268, "_repair_manager_registry", lambda target, module: calls.append((target, module)) or True)
    wrapped = v268._wrap_nonce_topology_probe(lambda: True)

    assert wrapped() is True
    assert calls == [(manager, _BrokerModule)]


def test_nonce_topology_probe_fails_closed_when_registry_repair_is_ambiguous(monkeypatch) -> None:
    manager = SimpleNamespace()

    monkeypatch.setattr(v268, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v268, "_broker_module", lambda: _BrokerModule)
    monkeypatch.setattr(v268, "_repair_manager_registry", lambda target, module: False)
    wrapped = v268._wrap_nonce_topology_probe(lambda: False)

    assert wrapped() is True


def test_install_does_not_relax_execution_nonce_killswitch_or_freshness(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_NONCE_READY", "0")
    monkeypatch.setenv("NIJA_KILL_SWITCH_ACTIVE", "1")
    monkeypatch.setenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90")
    before = {
        name: os.environ[name]
        for name in (
            "NIJA_RUNTIME_EXECUTION_AUTHORITY",
            "NIJA_NONCE_READY",
            "NIJA_KILL_SWITCH_ACTIVE",
            "NIJA_CAPITAL_FRESHNESS_TTL_S",
        )
    }

    monkeypatch.setattr(v268, "_patch_refresh_registry", lambda: True)
    monkeypatch.setattr(v268, "_patch_nonce_topology_probe", lambda: True)
    monkeypatch.setattr(v268, "_canonical_manager", lambda: None)
    monkeypatch.setattr(v268, "_patch_release_manifest", lambda: True)

    assert v268.install_import_hook() is True
    assert {name: os.environ[name] for name in before} == before
