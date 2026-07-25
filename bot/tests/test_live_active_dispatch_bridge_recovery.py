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


def _install_local_authority(
    monkeypatch, *, acquired: bool = True, lost: bool = False
):
    authority_module = ModuleType("bot.entrypoint_writer_authority")
    authority = type(
        "Authority",
        (),
        {"acquired": acquired, "lost": lost, "result": None},
    )()
    authority_module.get_entrypoint_writer_authority = lambda: authority
    monkeypatch.setitem(
        sys.modules,
        "bot.entrypoint_writer_authority",
        authority_module,
    )
    monkeypatch.delitem(sys.modules, "entrypoint_writer_authority", raising=False)
    return authority


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
    _install_local_authority(monkeypatch)
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
    _install_local_authority(monkeypatch)
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


def test_ensure_live_dispatch_starts_existing_strategy_only_when_ready(monkeypatch) -> None:
    module = _load_module()
    strategy = object()
    calls: list[tuple[object, str]] = []

    monkeypatch.setattr(module, "_loop_thread_running", lambda: False)
    monkeypatch.setattr(module, "_ensure_deferred_startup_repairs", lambda: (True, "ready"))
    monkeypatch.setattr(module, "_has_writer_authority", lambda: True)
    monkeypatch.setattr(module, "_runtime_execution_authority", lambda: True)
    monkeypatch.setattr(module, "_state_machine_live_active", lambda: True)
    monkeypatch.setattr(module, "_dispatch_allowed", lambda: (True, "ok"))
    monkeypatch.setattr(module, "_find_strategy", lambda: (strategy, "published"))
    monkeypatch.setattr(
        module,
        "_start_trading_loop",
        lambda candidate, source: calls.append((candidate, source)) or True,
    )

    started, detail = module.ensure_live_dispatch("watchdog")

    assert started is True
    assert detail == "started"
    assert calls == [(strategy, "published")]


def test_ensure_live_dispatch_recovers_missing_strategy_after_gates(monkeypatch) -> None:
    module = _load_module()
    strategy = type("Strategy", (), {"run_cycle": lambda self: None})()
    calls: list[tuple[object, str]] = []

    monkeypatch.setattr(module, "_loop_thread_running", lambda: False)
    monkeypatch.setattr(module, "_ensure_deferred_startup_repairs", lambda: (True, "ready"))
    monkeypatch.setattr(module, "_has_writer_authority", lambda: True)
    monkeypatch.setattr(module, "_runtime_execution_authority", lambda: True)
    monkeypatch.setattr(module, "_state_machine_live_active", lambda: True)
    monkeypatch.setattr(module, "_dispatch_allowed", lambda: (True, "ok"))
    monkeypatch.setattr(module, "_find_strategy", lambda: (None, "not_found"))
    monkeypatch.setattr(
        module,
        "_recover_strategy_publication",
        lambda: (strategy, "publication_recovery:built_published"),
    )
    monkeypatch.setattr(
        module,
        "_start_trading_loop",
        lambda candidate, source: calls.append((candidate, source)) or True,
    )

    started, detail = module.ensure_live_dispatch("watchdog")

    assert started is True
    assert detail == "started"
    assert calls == [(strategy, "publication_recovery:built_published")]


def test_ensure_live_dispatch_remains_fail_closed_when_recovery_fails(
    monkeypatch,
) -> None:
    module = _load_module()

    monkeypatch.setattr(module, "_loop_thread_running", lambda: False)
    monkeypatch.setattr(module, "_ensure_deferred_startup_repairs", lambda: (True, "ready"))
    monkeypatch.setattr(module, "_has_writer_authority", lambda: True)
    monkeypatch.setattr(module, "_runtime_execution_authority", lambda: True)
    monkeypatch.setattr(module, "_state_machine_live_active", lambda: True)
    monkeypatch.setattr(module, "_dispatch_allowed", lambda: (True, "ok"))
    monkeypatch.setattr(module, "_find_strategy", lambda: (None, "not_found"))
    monkeypatch.setattr(
        module,
        "_recover_strategy_publication",
        lambda: (None, "no_entry_ready_brokers"),
    )

    started, detail = module.ensure_live_dispatch("watchdog")

    assert started is False
    assert detail == "strategy_not_published"


def test_ensure_live_dispatch_skips_deferred_repairs_after_live_gates(monkeypatch) -> None:
    module = _load_module()
    strategy = object()

    monkeypatch.setattr(module, "_loop_thread_running", lambda: False)
    monkeypatch.setattr(module, "_has_writer_authority", lambda: True)
    monkeypatch.setattr(module, "_runtime_execution_authority", lambda: True)
    monkeypatch.setattr(module, "_state_machine_live_active", lambda: True)
    monkeypatch.setattr(
        module,
        "_ensure_deferred_startup_repairs",
        lambda: (_ for _ in ()).throw(
            AssertionError("live dispatch must not wait on deferred startup repair")
        ),
    )
    monkeypatch.setattr(module, "_dispatch_allowed", lambda: (True, "ok"))
    monkeypatch.setattr(module, "_find_strategy", lambda: (strategy, "published"))
    monkeypatch.setattr(module, "_start_trading_loop", lambda candidate, source: True)

    started, detail = module.ensure_live_dispatch("watchdog")

    assert started is True
    assert detail == "started"


def test_find_strategy_prefers_completed_position_sync_without_imports(monkeypatch) -> None:
    module = _load_module()
    strategy = object()
    sync_module = ModuleType("bot.startup_position_sync")
    sync_module._LAST_COMPLETED_STRATEGY = strategy
    monkeypatch.setitem(sys.modules, "bot.startup_position_sync", sync_module)
    monkeypatch.setattr(
        module,
        "_strategy_class",
        lambda: (_ for _ in ()).throw(
            AssertionError("completed strategy discovery must not import or resolve a class")
        ),
    )

    found, source = module._find_strategy()

    assert found is strategy
    assert source == "bot.startup_position_sync._LAST_COMPLETED_STRATEGY"


def test_find_strategy_returns_quickly_before_position_sync_completes(monkeypatch) -> None:
    module = _load_module()
    sync_module = ModuleType("bot.startup_position_sync")
    sync_module._LAST_COMPLETED_STRATEGY = None
    monkeypatch.setitem(sys.modules, "bot.startup_position_sync", sync_module)
    monkeypatch.setattr(module, "_strategy_from_initialized_state", lambda: (None, "not_found"))
    monkeypatch.setattr(module, "_strategy_class", lambda: None)

    found, detail = module._find_strategy()

    assert found is None
    assert detail == "strategy_not_published"


def test_writer_snapshot_rejects_standby_process_with_shared_token(monkeypatch) -> None:
    module = _load_module()
    authority_module = ModuleType("bot.entrypoint_writer_authority")
    authority = type(
        "Authority",
        (),
        {"acquired": False, "lost": False, "result": None},
    )()
    authority_module.get_entrypoint_writer_authority = lambda: authority
    monkeypatch.setitem(
        sys.modules,
        "bot.entrypoint_writer_authority",
        authority_module,
    )
    monkeypatch.delitem(sys.modules, "entrypoint_writer_authority", raising=False)
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1139")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "1800")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")

    snapshot = module._writer_authority_snapshot()

    assert snapshot["token_present"] is True
    assert snapshot["local_authority_observed"] is True
    assert snapshot["local_authority_acquired"] is False
    assert snapshot["ready"] is False


def test_writer_snapshot_accepts_only_locally_acquired_authority(monkeypatch) -> None:
    module = _load_module()
    authority_module = ModuleType("bot.entrypoint_writer_authority")
    authority = type(
        "Authority",
        (),
        {"acquired": True, "lost": False, "result": None},
    )()
    authority_module.get_entrypoint_writer_authority = lambda: authority
    monkeypatch.setitem(
        sys.modules,
        "bot.entrypoint_writer_authority",
        authority_module,
    )
    monkeypatch.delitem(sys.modules, "entrypoint_writer_authority", raising=False)
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1140")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "1801")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")

    snapshot = module._writer_authority_snapshot()

    assert snapshot["local_authority_acquired"] is True
    assert snapshot["local_authority_lost"] is False
    assert snapshot["ready"] is True
