from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


MODULE_PATH = Path(__file__).resolve().parents[1] / "render_startup_convergence_patch.py"


def _load_module():
    name = f"render_startup_convergence_patch_test_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _clear_runtime_env(monkeypatch):
    for key in (
        "LIVE_CAPITAL_VERIFIED",
        "DRY_RUN_MODE",
        "PAPER_MODE",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        "NIJA_RUNTIME_TRADING_STATE",
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_LEASE_GENERATION",
        "NIJA_WRITER_LEASE_ACQUIRED",
        "NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_stale_render_authority_is_reset_without_writer_lineage(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "true")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "true")

    module = _load_module()
    changes = module.normalize_derived_runtime_state()

    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
    assert os.environ["NIJA_WRITER_LEASE_ACQUIRED"] == "0"
    assert os.environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS"] == "1"
    assert "NIJA_RUNTIME_EXECUTION_AUTHORITY" in changes


def test_truthy_authority_is_canonicalized_after_writer_lineage(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "7")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "true")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "true")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")

    module = _load_module()
    module.normalize_derived_runtime_state()

    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "1"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "LIVE_ACTIVE"


def test_explicit_stricter_minimum_broker_requirement_is_preserved(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", "2")

    module = _load_module()
    module.normalize_derived_runtime_state()

    assert os.environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS"] == "2"


def test_recovery_refreshes_existing_manager_and_uses_normal_convergence(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-abc")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "3")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")

    calls = {"watchdog": 0, "refresh": 0, "converge": 0}

    class FakeManager:
        _fsm_initialized = True
        WATCHDOG_REFRESH_TRIGGER = "watchdog"

        @staticmethod
        def has_registered_sources():
            return True

        @staticmethod
        def has_attempted_connections():
            return True

        @staticmethod
        def _start_capital_watchdog():
            calls["watchdog"] += 1

        @staticmethod
        def refresh_capital_authority(*, trigger: str):
            calls["refresh"] += 1
            assert trigger == "watchdog"
            return {"ready": True, "total_capital": 75.0, "valid_brokers": 1}

    fake_manager_module = SimpleNamespace(get_broker_manager=lambda: FakeManager())
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", fake_manager_module)

    fake_convergence_module = SimpleNamespace()

    def converge(source: str):
        calls["converge"] += 1
        assert source == "render_post_lock_recovery"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
        return True

    fake_convergence_module.converge_runtime_authority = converge

    module = _load_module()
    original_import_module = module.importlib.import_module

    def import_module(name: str):
        if name == "bot.runtime_authority_convergence_repair_patch":
            return fake_convergence_module
        return original_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", import_module)

    done, reason = module._attempt_recovery_once()

    assert done is True
    assert reason == "converged_live_active"
    assert calls == {"watchdog": 1, "refresh": 1, "converge": 1}


def test_recovery_runs_canonical_prebootstrap_after_writer_lineage(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-recovery")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")

    calls = {"prepare": 0, "refresh": 0, "converge": 0}

    class FakeManager:
        _fsm_initialized = False
        WATCHDOG_REFRESH_TRIGGER = "watchdog"

        @staticmethod
        def has_registered_sources():
            return True

        @staticmethod
        def has_attempted_connections():
            return True

        @staticmethod
        def refresh_capital_authority(*, trigger: str):
            calls["refresh"] += 1
            assert trigger == "watchdog"
            return {"ready": True, "total_capital": 125.0, "valid_brokers": 1}

    manager = FakeManager()
    manager_module = SimpleNamespace(get_broker_manager=lambda: manager)
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", manager_module)

    def prepare():
        calls["prepare"] += 1
        manager._fsm_initialized = True
        return manager

    prebootstrap = SimpleNamespace(prepare_canonical_broker_runtime=prepare)
    monkeypatch.setitem(
        sys.modules,
        "nija_canonical_broker_prebootstrap_v22",
        prebootstrap,
    )

    convergence = SimpleNamespace()

    def converge(source: str):
        calls["converge"] += 1
        assert source == "render_post_lock_recovery"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
        return True

    convergence.converge_runtime_authority = converge

    module = _load_module()
    original_import_module = module.importlib.import_module

    def import_module(name: str):
        if name == "bot.runtime_authority_convergence_repair_patch":
            return convergence
        return original_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", import_module)

    done, reason = module._attempt_recovery_once()

    assert done is True
    assert reason == "converged_live_active"
    assert manager._fsm_initialized is True
    assert calls == {"prepare": 1, "refresh": 1, "converge": 1}


def test_recovery_loads_prebootstrap_from_launcher_guard(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-launcher")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "11")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")

    manager = SimpleNamespace(_fsm_initialized=False)
    monkeypatch.setitem(
        sys.modules,
        "bot.multi_account_broker_manager",
        SimpleNamespace(get_broker_manager=lambda: manager),
    )
    monkeypatch.delitem(
        sys.modules,
        "nija_canonical_broker_prebootstrap_v22",
        raising=False,
    )
    monkeypatch.delitem(
        sys.modules,
        "bot.canonical_broker_prebootstrap_v22",
        raising=False,
    )

    calls = {"load": 0, "prepare": 0}

    def prepare():
        calls["prepare"] += 1
        manager._fsm_initialized = True
        return manager

    def load():
        calls["load"] += 1
        return SimpleNamespace(prepare_canonical_broker_runtime=prepare)

    monkeypatch.setitem(
        sys.modules,
        "nija_canonical_broker_startup_convergence_v24_prebot",
        SimpleNamespace(_load_v22_module=load),
    )

    module = _load_module()
    recovered, reason = module._canonical_prebootstrap_manager()

    assert recovered is manager
    assert reason == "canonical_prebootstrap_ready"
    assert calls == {"load": 1, "prepare": 1}


def test_recovery_keeps_failed_canonical_prebootstrap_fail_closed(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-failed")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "10")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")

    manager = SimpleNamespace(_fsm_initialized=False)
    monkeypatch.setitem(
        sys.modules,
        "bot.multi_account_broker_manager",
        SimpleNamespace(get_broker_manager=lambda: manager),
    )

    def fail():
        raise RuntimeError("broker credentials rejected")

    monkeypatch.setitem(
        sys.modules,
        "nija_canonical_broker_prebootstrap_v22",
        SimpleNamespace(prepare_canonical_broker_runtime=fail),
    )

    module = _load_module()
    done, reason = module._attempt_recovery_once()

    assert done is False
    assert reason == "canonical_prebootstrap_failed:RuntimeError"
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"


def test_recovery_does_not_import_or_initialize_brokers_before_writer_lineage(monkeypatch):
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "true")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.delitem(sys.modules, "bot.multi_account_broker_manager", raising=False)
    monkeypatch.delitem(sys.modules, "multi_account_broker_manager", raising=False)

    module = _load_module()
    done, reason = module._attempt_recovery_once()

    assert done is False
    assert reason == "fencing_token_missing"
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
