from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

import source_runtime_guard_bootstrap as source_bootstrap


def _reset_source_bootstrap(monkeypatch) -> None:
    monkeypatch.setattr(source_bootstrap, "_INSTALLED", False)
    monkeypatch.delenv("NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP", raising=False)
    monkeypatch.delenv("NIJA_VENUE_READINESS_SOURCE_MARKER", raising=False)
    monkeypatch.delenv("NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED", raising=False)
    monkeypatch.delenv("NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED", raising=False)
    monkeypatch.delenv("NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALLED", raising=False)
    monkeypatch.delenv("NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED", raising=False)
    monkeypatch.delenv("NIJA_RENDER_READINESS_BRIDGE_INSTALLED", raising=False)


def test_source_bootstrap_installs_writer_before_required_guards_once(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    calls: list[str] = []
    fake_writer = ModuleType("prebot_writer_authority_fail_closed")
    fake_writer.install = lambda: calls.append("writer")
    fake_repair = ModuleType("venue_readiness_execution_repair_patch")
    fake_repair.install = lambda: calls.append("venue")
    fake_activator = ModuleType("secondary_venue_activation_patch")
    fake_activator.install = lambda: calls.append("activator")
    fake_strict = ModuleType("secondary_venue_strict_readiness_patch")
    fake_strict.install = lambda: calls.append("strict")
    fake_exit_recovery = ModuleType("account_exit_management_recovery_patch")
    fake_exit_recovery.install_import_hook = lambda: calls.append("exit_recovery")
    fake_stage = ModuleType("three_venue_execution_readiness")
    fake_stage.install = lambda: calls.append("stage")
    fake_bridge = ModuleType("render_readiness_state_bridge")
    fake_bridge.install = lambda: calls.append("bridge")

    modules = {
        "prebot_writer_authority_fail_closed": fake_writer,
        "venue_readiness_execution_repair_patch": fake_repair,
        "secondary_venue_activation_patch": fake_activator,
        "secondary_venue_strict_readiness_patch": fake_strict,
        "account_exit_management_recovery_patch": fake_exit_recovery,
        "three_venue_execution_readiness": fake_stage,
        "render_readiness_state_bridge": fake_bridge,
    }
    real_import = source_bootstrap.importlib.import_module

    def _fake_import(name: str):
        return modules.get(name) or real_import(name)

    monkeypatch.setattr(source_bootstrap.importlib, "import_module", _fake_import)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    assert source_bootstrap.install() is True
    assert source_bootstrap.install() is True
    assert calls == ["writer", "venue", "activator", "strict", "exit_recovery", "stage", "bridge"]
    assert source_bootstrap.installed_marker() == "20260710af"
    assert source_bootstrap.os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] == "1"
    assert source_bootstrap.os.environ["NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_RENDER_READINESS_BRIDGE_INSTALLED"] == "1"


def test_source_bootstrap_live_failure_raises_system_exit(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    def _broken_import(_name: str):
        raise ImportError("repair missing")

    monkeypatch.setattr(source_bootstrap.importlib, "import_module", _broken_import)

    with pytest.raises(SystemExit) as exc_info:
        source_bootstrap.install()

    assert exc_info.value.code == 78
    assert source_bootstrap.os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP"] == "0"
    assert source_bootstrap.os.environ["NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_RENDER_READINESS_BRIDGE_INSTALLED"] == "0"


def test_global_startup_guards_install_source_repair_before_other_guards(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    path = root / "bot" / "global_runtime_startup_guards.py"
    spec = importlib.util.spec_from_file_location("nija_test_global_runtime_startup_guards", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    order: list[str] = []
    fake_source = ModuleType("source_runtime_guard_bootstrap")
    fake_source.install = lambda: order.append("source") or True

    real_import = module.importlib.import_module

    def _fake_import(name: str):
        if name == "source_runtime_guard_bootstrap":
            return fake_source
        return real_import(name)

    monkeypatch.setattr(module.importlib, "import_module", _fake_import)
    monkeypatch.setattr(module, "_set_defaults", lambda: order.append("defaults"))
    monkeypatch.setattr(module, "_install_kraken_patch_log_dedupe", lambda: order.append("dedupe"))
    monkeypatch.setattr(
        module,
        "_install_module",
        lambda module_name, marker: order.append(module_name) or True,
    )
    monkeypatch.delattr(
        builtins,
        "_NIJA_GLOBAL_RUNTIME_STARTUP_GUARDS_20260706B",
        raising=False,
    )

    module.install()

    assert order[0] == "source"
    assert order[1] == "defaults"
    assert "held_trade_cap_guard_patch" in order
