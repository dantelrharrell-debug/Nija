from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType


def _load_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "bot" / "live_active_dispatch_bridge_patch.py"
    spec = importlib.util.spec_from_file_location(
        "nija_test_live_active_dispatch_bridge_recovery", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_broker_bootstrap_accepts_active_broker_manager_alias(monkeypatch) -> None:
    module = _load_module()
    for name in module._BROKER_MODULE_NAMES:
        monkeypatch.delitem(sys.modules, name, raising=False)

    broker_manager = ModuleType("bot.broker_manager")
    broker_manager.OKXBroker = type("OKXBroker", (), {})
    monkeypatch.setitem(sys.modules, "bot.broker_manager", broker_manager)

    loaded, source = module._broker_bootstrap_loaded()

    assert loaded is True
    assert source == "bot.broker_manager"


def test_deferred_repairs_install_after_broker_manager_load(monkeypatch) -> None:
    module = _load_module()
    for name in module._BROKER_MODULE_NAMES:
        monkeypatch.delitem(sys.modules, name, raising=False)

    broker_manager = ModuleType("bot.broker_manager")
    monkeypatch.setitem(sys.modules, "bot.broker_manager", broker_manager)

    ready_event = threading.Event()
    activation = ModuleType("bot.activation_pending_commit_monitor_patch")
    activation._STARTUP_REPAIRS_READY = ready_event
    calls: list[str] = []

    def install() -> bool:
        calls.append("install")
        ready_event.set()
        return True

    activation._install_startup_execution_repairs = install
    monkeypatch.setitem(
        sys.modules, "bot.activation_pending_commit_monitor_patch", activation
    )

    ready, detail = module._ensure_deferred_startup_repairs()

    assert ready is True
    assert detail == "installed"
    assert calls == ["install"]


def test_writer_authority_is_separate_from_runtime_authority(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")
    monkeypatch.setattr(module, "_loop_thread_running", lambda: False)
    monkeypatch.setattr(module, "_state_machine_live_active", lambda: False)

    snapshot = module._writer_authority_snapshot()
    allowed, reason = module._dispatch_allowed()

    assert snapshot["ready"] is True
    assert snapshot["runtime_auth"] is False
    assert allowed is False
    assert reason == "runtime_execution_authority_missing"


def test_runtime_convergence_uses_existing_fail_closed_repair(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")

    convergence = ModuleType("bot.runtime_authority_convergence_repair_patch")
    calls: list[str] = []

    def install_import_hook() -> None:
        calls.append("install")

    def converge(source: str) -> bool:
        calls.append(source)
        monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
        monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
        return True

    convergence.install_import_hook = install_import_hook
    convergence.converge_runtime_authority = converge
    monkeypatch.setitem(
        sys.modules, "bot.runtime_authority_convergence_repair_patch", convergence
    )
    monkeypatch.setattr(
        module,
        "_state_machine_live_active",
        lambda: module._truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
        and module.os.environ.get("NIJA_RUNTIME_TRADING_STATE") == "LIVE_ACTIVE",
    )

    ready, detail = module._attempt_runtime_convergence("test")

    assert ready is True
    assert detail == "ready"
    assert calls == ["install", "test"]
