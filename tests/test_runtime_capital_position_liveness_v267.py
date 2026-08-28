from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

from bot import runtime_capital_position_liveness_v267_patch as v267


class _FakeThread:
    def __init__(self, *, alive: bool = True, name: str = "") -> None:
        self._alive = alive
        self.name = name

    def is_alive(self) -> bool:
        return self._alive


class _FakeStop:
    def is_set(self) -> bool:
        return False


class _Manager:
    def __init__(self) -> None:
        self._capital_watchdog_stop = _FakeStop()
        self._nija_capital_publication_deadline_v137_started = False
        self._all_user_brokers = {}
        self.user_brokers = {}
        self._user_metadata = {}
        self._failed_user_connections = {}
        self._users_without_credentials = {}
        self.prepare_calls = 0

    def prepare_users_from_config(self) -> int:
        self.prepare_calls += 1
        self._user_metadata["configured-user"] = {"brokers": {"kraken": False}}
        return 1


def test_v137_stale_boolean_latch_is_not_liveness_proof(monkeypatch) -> None:
    manager = _Manager()
    manager._nija_capital_publication_deadline_v137_started = True
    calls: list[object] = []

    class FakeV137:
        @staticmethod
        def _start_deadline_monitor(target):
            calls.append(target)
            target._nija_capital_publication_deadline_v137_started = True
            target._nija_capital_publication_deadline_v137_thread = _FakeThread(
                alive=True,
                name="capital-publication-deadline-v137",
            )
            return True

    monkeypatch.setattr(v267.importlib, "import_module", lambda name: FakeV137 if name == "bot.capital_publication_deadline_v137_patch" else __import__(name, fromlist=["*"]))
    monkeypatch.setattr(v267, "_find_v137_thread", lambda target: getattr(target, v267._V137_THREAD_ATTR, None) if v267._alive(getattr(target, v267._V137_THREAD_ATTR, None)) else None)

    assert v267._patch_v137_monitor() is True
    assert FakeV137._start_deadline_monitor(manager) is True
    assert calls == [manager]
    assert manager._nija_capital_publication_deadline_v137_started is True


def test_v137_live_thread_prevents_duplicate_start(monkeypatch) -> None:
    manager = _Manager()
    live = _FakeThread(alive=True, name="capital-publication-deadline-v137")
    setattr(manager, v267._V137_THREAD_ATTR, live)
    manager._nija_capital_publication_deadline_v137_started = True
    calls: list[object] = []

    class FakeV137:
        @staticmethod
        def _start_deadline_monitor(target):
            calls.append(target)
            return True

    monkeypatch.setattr(v267.importlib, "import_module", lambda name: FakeV137 if name == "bot.capital_publication_deadline_v137_patch" else __import__(name, fromlist=["*"]))
    monkeypatch.setattr(v267, "_find_v137_thread", lambda target: live)

    assert v267._patch_v137_monitor() is True
    assert FakeV137._start_deadline_monitor(manager) is True
    assert calls == []


def test_v108_stale_active_key_clears_only_after_missing_worker_grace(monkeypatch) -> None:
    manager = _Manager()
    broker = SimpleNamespace(connected=True, _startup_position_sync_adopted=False)
    key = (id(manager), id(broker))
    fake_lock = threading.RLock()
    fake_v108 = SimpleNamespace(
        _ACTIVE={key},
        _LOCK=fake_lock,
        _connected_unsynced_platform_brokers=lambda _manager: [("kraken", broker)],
    )

    monkeypatch.setattr(v267, "_position_worker_alive", lambda _key, _name: False)
    monkeypatch.setattr(v267, "_position_worker_grace_s", lambda: 5.0)
    v267._POSITION_ACTIVE_MISSING_SINCE.clear()

    assert v267._clear_stale_v108_active(manager, fake_v108) == 0
    assert key in fake_v108._ACTIVE

    v267._POSITION_ACTIVE_MISSING_SINCE[key] = time.monotonic() - 6.0
    assert v267._clear_stale_v108_active(manager, fake_v108) == 1
    assert key not in fake_v108._ACTIVE
    assert broker._startup_position_sync_adopted is False


def test_v108_live_worker_keeps_singleflight(monkeypatch) -> None:
    manager = _Manager()
    broker = SimpleNamespace(connected=True, _startup_position_sync_adopted=False)
    key = (id(manager), id(broker))
    fake_v108 = SimpleNamespace(
        _ACTIVE={key},
        _LOCK=threading.RLock(),
        _connected_unsynced_platform_brokers=lambda _manager: [("kraken", broker)],
    )
    monkeypatch.setattr(v267, "_position_worker_alive", lambda _key, _name: True)
    v267._POSITION_ACTIVE_MISSING_SINCE[key] = time.monotonic() - 60.0

    assert v267._clear_stale_v108_active(manager, fake_v108) == 0
    assert key in fake_v108._ACTIVE


def test_empty_canonical_registry_is_rehydrated_registration_only(monkeypatch) -> None:
    manager = _Manager()
    monkeypatch.setattr(v267, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v267, "_enabled_kraken_user_count", lambda: 2)
    monkeypatch.setattr(v267, "_registered_user_count", lambda target: 1 if target._user_metadata else 0)
    v267._USER_REHYDRATE_NEXT_AT.clear()

    assert v267._rehydrate_user_registry() is True
    assert manager.prepare_calls == 1
    assert manager._user_metadata


def test_partial_user_registry_is_never_replaced(monkeypatch) -> None:
    manager = _Manager()
    manager._failed_user_connections[("one", "kraken")] = "auth_failed"
    monkeypatch.setattr(v267, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v267, "_enabled_kraken_user_count", lambda: 2)
    monkeypatch.setattr(v267, "_registered_user_count", lambda _target: 0)

    assert v267._rehydrate_user_registry() is True
    assert manager.prepare_calls == 0
    assert manager._failed_user_connections[("one", "kraken")] == "auth_failed"


def test_v267_does_not_mutate_execution_nonce_killswitch_or_freshness(monkeypatch) -> None:
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
    monkeypatch.setattr(v267, "_patch_v137_monitor", lambda: True)
    monkeypatch.setattr(v267, "_patch_v108_dispatch", lambda: True)
    monkeypatch.setattr(v267, "_patch_release_manifest", lambda: True)
    monkeypatch.setattr(v267, "_ensure_v137_monitor", lambda: True)
    monkeypatch.setattr(v267, "_rehydrate_user_registry", lambda: True)

    assert v267.install_import_hook() is True
    assert {name: os.environ[name] for name in before} == before
