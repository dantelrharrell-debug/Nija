from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "bot" / "runtime_execution_convergence_v32.py"


def _load_module(name: str = "nija_test_runtime_execution_convergence_v32"):
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unwrap_callable_stops_at_deepest_noncyclic_callable():
    module = _load_module()

    def base():
        return True

    def wrapper():
        return base()

    wrapper.__wrapped__ = base
    assert module._unwrap_callable(wrapper) is base


def test_writer_ready_requires_complete_lineage(monkeypatch):
    module = _load_module("nija_test_runtime_execution_convergence_writer")
    monkeypatch.delenv("NIJA_WRITER_FENCING_TOKEN", raising=False)
    monkeypatch.delenv("NIJA_WRITER_LEASE_GENERATION", raising=False)
    monkeypatch.delenv("NIJA_WRITER_LEASE_ACQUIRED", raising=False)
    assert module._writer_ready() is False

    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "4")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    assert module._writer_ready() is True


def test_reconnect_patch_blocks_reentry_and_reconciles(monkeypatch):
    module = _load_module("nija_test_runtime_execution_convergence_reentry")
    calls: list[str] = []

    class Manager:
        def __init__(self):
            self.broker_name = "coinbase_platform"
            self._reconnect_fn = lambda: True

        def register_broker(self, broker, reconnect_fn, *args, **kwargs):
            self._reconnect_fn = reconnect_fn

        def register_pre_reconnect_hook(self, hook):
            return None

        def register_reconnect_hook(self, hook):
            return None

        def _attempt_reconnect(self):
            calls.append("attempt")
            return True

    fake_module = SimpleNamespace(
        __name__="bot.connection_stability_manager",
        ConnectionStabilityManager=Manager,
    )
    monkeypatch.setattr(module, "_request_runtime_reconciliation", lambda trigger: calls.append(trigger) or True)

    assert module._patch_connection_stability(fake_module) is True
    manager = Manager()
    assert manager._attempt_reconnect() is True
    assert calls == ["attempt", "coinbase_platform_reconnect_success"]

    manager._nija_reconnect_guard.acquire()
    try:
        assert manager._attempt_reconnect() is False
    finally:
        manager._nija_reconnect_guard.release()


def test_install_hook_attests(monkeypatch):
    module = _load_module("nija_test_runtime_execution_convergence_install")
    monkeypatch.delenv("NIJA_RUNTIME_EXECUTION_CONVERGENCE_V32_INSTALLED", raising=False)
    assert module.install_import_hook() is True
    assert module.os.environ["NIJA_RUNTIME_EXECUTION_CONVERGENCE_V32_INSTALLED"] == "1"
