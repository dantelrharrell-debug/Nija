from __future__ import annotations

import os
import threading
from types import ModuleType, SimpleNamespace

from bot import kraken_read_timeout_v121_patch as v121
from bot import runtime_kraken_credential_lock_scope_v293_patch as v293


class _Broker:
    def __init__(self, key: str | None):
        self.api = SimpleNamespace(key=key) if key is not None else SimpleNamespace()
        self.account_identifier = key or "unknown"


def _reset_v293() -> None:
    with v293._LOCK:
        v293._SCOPE_LOCKS.clear()
    for name in ("lock", "scope"):
        try:
            delattr(v293._SCOPE_LOCAL, name)
        except AttributeError:
            pass


def test_v121_detects_existing_patch_anywhere_in_wrapper_chain():
    def base():
        return None

    def inner():
        return base()

    setattr(inner, v121._PATCH_ATTR, True)
    setattr(inner, "__wrapped__", base)

    def outer():
        return inner()

    setattr(outer, "__wrapped__", inner)
    assert v121._chain_has_patch(outer) is True


def test_v121_enters_v293_credential_scope_before_lock_selection(monkeypatch):
    _reset_v293()
    fallback = threading.RLock()
    module = ModuleType("fake_broker_manager")
    module.get_kraken_api_lock = v293._scoped_get_kraken_api_lock
    monkeypatch.setattr(v293, "_ORIGINAL_GET_LOCK", lambda: fallback)
    monkeypatch.setitem(
        __import__("sys").modules,
        "bot.runtime_kraken_credential_lock_scope_v293_patch",
        v293,
    )

    broker = _Broker("platform-key")
    observed = []

    def call():
        observed.append(v293._scoped_get_kraken_api_lock())
        return "ok"

    assert v121._invoke_bounded_read(module, broker, "Balance", call) == "ok"
    expected = v293._scoped_lock(v293._credential_scope_key(broker))
    assert observed == [expected]
    assert expected is not fallback


def test_v121_falls_back_to_global_lock_when_credential_unproven(monkeypatch):
    _reset_v293()
    fallback = threading.RLock()
    module = ModuleType("fake_broker_manager")
    module.get_kraken_api_lock = v293._scoped_get_kraken_api_lock
    monkeypatch.setattr(v293, "_ORIGINAL_GET_LOCK", lambda: fallback)
    monkeypatch.setitem(
        __import__("sys").modules,
        "bot.runtime_kraken_credential_lock_scope_v293_patch",
        v293,
    )

    broker = _Broker(None)
    observed = []

    def call():
        observed.append(v293._scoped_get_kraken_api_lock())
        return "ok"

    assert v121._invoke_bounded_read(module, broker, "Balance", call) == "ok"
    assert observed == [fallback]


def test_v311_installs_read_liveness_subset_in_declared_order(monkeypatch):
    monkeypatch.delenv(v121._EARLY_READ_READY_FLAG, raising=False)
    imported = []

    class _FakeModule:
        @staticmethod
        def install_import_hook():
            return True

    def fake_import(name: str):
        imported.append(name)
        return _FakeModule()

    monkeypatch.setattr(v121.importlib, "import_module", fake_import)

    assert v121._install_early_read_convergence_v311() is True
    assert imported == list(v121._EARLY_READ_MODULES)
    assert os.environ[v121._EARLY_READ_READY_FLAG] == "1"


def test_v311_failure_stays_fail_closed_and_retryable(monkeypatch):
    monkeypatch.delenv(v121._EARLY_READ_READY_FLAG, raising=False)
    imported = []

    class _Ready:
        @staticmethod
        def install_import_hook():
            return True

    class _NotReady:
        @staticmethod
        def install_import_hook():
            return False

    def fake_import(name: str):
        imported.append(name)
        return _NotReady() if len(imported) == 2 else _Ready()

    monkeypatch.setattr(v121.importlib, "import_module", fake_import)

    assert v121._install_early_read_convergence_v311() is False
    assert imported == list(v121._EARLY_READ_MODULES[:2])
    assert os.environ[v121._EARLY_READ_READY_FLAG] == "0"

    imported.clear()
    monkeypatch.setattr(v121.importlib, "import_module", lambda name: imported.append(name) or _Ready())
    assert v121._install_early_read_convergence_v311() is True
    assert imported == list(v121._EARLY_READ_MODULES)
    assert os.environ[v121._EARLY_READ_READY_FLAG] == "1"
