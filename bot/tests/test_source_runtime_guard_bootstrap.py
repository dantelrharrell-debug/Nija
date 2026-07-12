from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

import source_runtime_guard_bootstrap as source_bootstrap


def _reset_source_bootstrap(monkeypatch) -> None:
    monkeypatch.setattr(source_bootstrap, "_INSTALLED", False)
    for name in (
        "NIJA_VENUE_READINESS_SOURCE_BOOTSTRAP",
        "NIJA_VENUE_READINESS_SOURCE_MARKER",
        "NIJA_BROKER_AUTH_RECOVERY_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_HARDENING_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_V2_INSTALLED",
        "NIJA_RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED",
        "NIJA_FINAL_RUNTIME_CONVERGENCE_INSTALLED",
        "NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED",
        "NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED",
        "NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALLED",
        "NIJA_ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_INSTALLED",
        "NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED",
        "NIJA_RENDER_READINESS_BRIDGE_INSTALLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_source_bootstrap_installs_writer_and_convergence_before_broker_activation(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    calls: list[str] = []
    names = (
        ("prebot_writer_authority_fail_closed", "writer", "install"),
        ("broker_auth_recovery_patch", "auth", "install"),
        ("runtime_convergence_hardening_patch", "convergence", "install"),
        ("runtime_convergence_v2_patch", "convergence_v2", "install"),
        ("runtime_auth_recursion_endpoint_repair_patch", "auth_endpoint", "install"),
        ("final_runtime_convergence_patch", "final_convergence", "install"),
        ("venue_readiness_execution_repair_patch", "venue", "install"),
        ("secondary_venue_activation_patch", "activator", "install"),
        ("secondary_venue_strict_readiness_patch", "strict", "install"),
        ("account_exit_management_recovery_patch", "exit_recovery", "install_import_hook"),
        ("account_exit_recovery_bootstrap_patch", "exit_bootstrap", "install"),
        ("three_venue_execution_readiness", "stage", "install"),
        ("render_readiness_state_bridge", "bridge", "install"),
    )
    modules = {}
    for module_name, label, installer_name in names:
        module = ModuleType(module_name)
        setattr(module, installer_name, lambda label=label: calls.append(label))
        modules[module_name] = module

    real_import = source_bootstrap.importlib.import_module
    monkeypatch.setattr(
        source_bootstrap.importlib,
        "import_module",
        lambda name: modules.get(name) or real_import(name),
    )
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    assert source_bootstrap.install() is True
    assert source_bootstrap.install() is True
    assert calls == [
        "writer", "auth", "convergence", "convergence_v2", "auth_endpoint",
        "final_convergence", "venue", "activator", "strict", "exit_recovery",
        "exit_bootstrap", "stage", "bridge",
    ]
    assert source_bootstrap.installed_marker() == "20260712d"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_CONVERGENCE_HARDENING_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_CONVERGENCE_V2_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_FINAL_RUNTIME_CONVERGENCE_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_BROKER_AUTH_RECOVERY_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] == "1"


def test_source_bootstrap_live_failure_raises_system_exit(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setattr(
        source_bootstrap.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("repair missing")),
    )

    with pytest.raises(SystemExit) as exc_info:
        source_bootstrap.install()

    assert exc_info.value.code == 78
    assert source_bootstrap.os.environ["NIJA_RUNTIME_CONVERGENCE_HARDENING_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_CONVERGENCE_V2_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_FINAL_RUNTIME_CONVERGENCE_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] == "0"


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
    monkeypatch.setattr(
        module.importlib,
        "import_module",
        lambda name: fake_source if name == "source_runtime_guard_bootstrap" else real_import(name),
    )
    monkeypatch.setattr(module, "_set_defaults", lambda: order.append("defaults"))
    monkeypatch.setattr(module, "_install_kraken_patch_log_dedupe", lambda: order.append("dedupe"))
    monkeypatch.setattr(module, "_install_module", lambda module_name, marker: order.append(module_name) or True)
    monkeypatch.delattr(builtins, "_NIJA_GLOBAL_RUNTIME_STARTUP_GUARDS_20260706B", raising=False)

    module.install()

    assert order[0] == "source"
    assert order[1] == "defaults"
    assert "held_trade_cap_guard_patch" in order
