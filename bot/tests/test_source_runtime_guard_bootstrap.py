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
        "NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED",
        "NIJA_RUNTIME_MODULE_IDENTITY_READY",
        "NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED",
        "NIJA_ZERO_SIGNAL_STREAK_STATE_READY",
        "NIJA_BROKER_AUTH_RECOVERY_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_HARDENING_INSTALLED",
        "NIJA_RUNTIME_CONVERGENCE_V2_INSTALLED",
        "NIJA_RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED",
        "NIJA_FINAL_RUNTIME_CONVERGENCE_INSTALLED",
        "NIJA_SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED",
        "NIJA_SCAN_OWNER_OKX_AUTH_CONVERGENCE_INSTALLED",
        "NIJA_WRITER_GENERATION_SCOPE_REPAIR_INSTALLED",
        "NIJA_AUTHORITY_HEARTBEAT_GENERATION_SCOPE_INSTALLED",
        "NIJA_FINAL_WORKER_POSITION_COINBASE_REPAIR_INSTALLED",
        "NIJA_SECONDARY_VENUE_ACTIVATOR_INSTALLED",
        "NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED",
        "NIJA_BROKER_LOCAL_READINESS_CONTRACT_INSTALLED",
        "NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALLED",
        "NIJA_ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_INSTALLED",
        "NIJA_THREE_VENUE_STAGE_VERIFIER_INSTALLED",
        "NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED",
        "NIJA_RENDER_READINESS_BRIDGE_INSTALLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_source_bootstrap_installs_module_identity_and_streak_repair_before_core_runtime(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    calls: list[str] = []
    names = (
        ("prebot_writer_authority_fail_closed", "writer", "install"),
        ("runtime_module_identity_convergence_patch", "module_identity", "install"),
        ("writer_generation_scope_repair_patch", "generation_scope", "install"),
        ("authority_heartbeat_generation_scope_patch", "heartbeat_scope", "install"),
        ("final_worker_position_coinbase_repair_patch", "worker_position", "install"),
        ("broker_auth_recovery_patch", "auth", "install"),
        ("runtime_convergence_hardening_patch", "convergence", "install"),
        ("bot.zero_signal_streak_state_repair_patch", "zero_signal_state", "install"),
        ("runtime_convergence_v2_patch", "convergence_v2", "install"),
        ("runtime_auth_recursion_endpoint_repair_patch", "auth_endpoint", "install"),
        ("final_runtime_convergence_patch", "final_convergence", "install"),
        ("scan_wrapper_convergence_repair_patch", "scan_wrapper", "install"),
        ("venue_readiness_execution_repair_patch", "venue", "install"),
        ("secondary_venue_activation_patch", "activator", "install"),
        ("secondary_venue_strict_readiness_patch", "strict", "install"),
        ("broker_local_readiness_contract_patch", "broker_local_contract", "install"),
        ("account_exit_management_recovery_patch", "exit_recovery", "install_import_hook"),
        ("account_exit_recovery_bootstrap_patch", "exit_bootstrap", "install"),
        ("three_venue_execution_readiness", "stage", "install"),
        ("render_readiness_state_bridge", "bridge", "install"),
        ("scan_owner_okx_auth_convergence_patch", "scan_owner", "install"),
    )
    modules = {}
    for module_name, label, installer_name in names:
        module = ModuleType(module_name)
        setattr(module, installer_name, lambda label=label: calls.append(label))
        if module_name == "runtime_module_identity_convergence_patch":
            module.audit = lambda: (True, {"identity": "ready"})
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
        "writer", "module_identity", "generation_scope", "heartbeat_scope",
        "worker_position", "auth", "convergence", "zero_signal_state",
        "convergence_v2", "auth_endpoint", "final_convergence", "scan_wrapper",
        "venue", "activator", "strict", "broker_local_contract",
        "exit_recovery", "exit_bootstrap", "stage", "bridge", "scan_owner",
    ]
    assert calls.index("module_identity") < calls.index("convergence")
    assert calls.index("zero_signal_state") < calls.index("convergence_v2")
    assert calls.index("broker_local_contract") < calls.index("bridge")
    assert source_bootstrap.installed_marker() == "20260714d"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_WRITER_GENERATION_SCOPE_REPAIR_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED"] == "1"
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
    assert source_bootstrap.os.environ["NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] == "0"
    assert source_bootstrap.os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_REPAIR_INSTALLED"] == "0"
    assert source_bootstrap.os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] == "0"
    assert source_bootstrap.os.environ["NIJA_WRITER_GENERATION_SCOPE_REPAIR_INSTALLED"] == "0"
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
