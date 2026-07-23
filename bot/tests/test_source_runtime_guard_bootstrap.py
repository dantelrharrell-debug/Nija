from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

import source_runtime_guard_bootstrap as source_bootstrap


def _reset_source_bootstrap(monkeypatch) -> None:
    monkeypatch.setattr(source_bootstrap, "_INSTALLED", False)
    for name in tuple(source_bootstrap.os.environ):
        if name.startswith("NIJA_") and name != "NIJA_DEFER_RUNTIME_SITE_HOOKS":
            monkeypatch.delenv(name, raising=False)


def _fake_runtime_modules(calls: list[str]) -> tuple[dict[str, ModuleType], list[str]]:
    specs = (
        ("prebot_writer_authority_fail_closed", "writer", "install"),
        ("scan_wrapper_depth_convergence_patch", "scan_depth", "install"),
        ("writer_generation_scope_repair_patch", "generation_scope", "install"),
        ("authority_heartbeat_generation_scope_patch", "heartbeat_scope", "install"),
        ("final_worker_position_coinbase_repair_patch", "worker_position", "install"),
        ("bot.okx_regional_endpoint_isolation_patch", "okx_endpoint", "install"),
        ("broker_auth_recovery_patch", "auth", "install"),
        ("bot.coinbase_funding_readiness_repair_patch", "coinbase_funding", "install"),
        ("bot.okx_funding_wallet_readiness_patch", "okx_funding", "install"),
        ("bot.secondary_credential_quarantine_patch", "credential_quarantine", "install"),
        ("runtime_convergence_hardening_patch", "convergence", "install"),
        ("bot.zero_signal_streak_state_repair_patch", "zero_signal_state", "install"),
        ("bot.empty_position_sync_success_patch", "empty_position_sync", "install"),
        ("runtime_convergence_v2_patch", "convergence_v2", "install"),
        ("runtime_auth_recursion_endpoint_repair_patch", "auth_endpoint", "install"),
        ("final_runtime_convergence_patch", "final_convergence", "install"),
        ("scan_wrapper_convergence_repair_patch", "scan_wrapper", "install"),
        ("bot.scan_reentrant_delegate_repair_patch", "scan_delegate", "install"),
        ("bot.scan_wrapper_hard_clamp_patch", "scan_clamp", "install"),
        ("venue_readiness_execution_repair_patch", "venue", "install"),
        ("secondary_venue_activation_patch", "activator", "install"),
        ("secondary_venue_strict_readiness_patch", "strict", "install"),
        ("broker_local_readiness_contract_patch", "broker_local_contract", "install"),
        ("runtime_live_broker_state_convergence_patch", "live_broker_state", "install"),
        ("account_exit_management_recovery_patch", "exit_recovery", "install_import_hook"),
        ("account_exit_recovery_bootstrap_patch", "exit_bootstrap", "install"),
        ("bot.kraken_verified_cost_basis_recovery_patch", "kraken_cost_basis", "install"),
        ("bot.daily_gain_profit_harvest_patch", "profit_harvest", "install"),
        ("bot.kraken_tpe_min_notional_allocation_patch", "kraken_tpe", "install"),
        ("bot.account_scope_exit_integrity_final_patch", "account_exit_integrity", "install"),
        ("three_venue_execution_readiness", "stage", "install"),
        ("render_readiness_state_bridge", "bridge", "install"),
        ("scan_owner_okx_auth_convergence_patch", "scan_owner", "install"),
        ("bot.downstream_risk_governor_equity_repair_patch", "downstream_risk", "install"),
        ("runtime_module_identity_convergence_patch", "module_identity", "install"),
        ("runtime_convergence_quiescence_patch", "quiescence", "install"),
        ("bot.runtime_post_import_convergence_patch", "post_import", "install"),
        ("bot.runtime_guard_audit_patch", "guard_audit", "install"),
    )

    modules: dict[str, ModuleType] = {}
    expected: list[str] = []
    for module_name, label, installer_name in specs:
        module = ModuleType(module_name)
        setattr(module, installer_name, lambda label=label: calls.append(label))
        expected.append(label)

        if module_name == "runtime_module_identity_convergence_patch":
            module.audit = lambda: (True, {"identity": "ready"})
        elif module_name == "runtime_convergence_quiescence_patch":
            module.audit = lambda: (True, {"quiescence": "ready"})
        elif module_name == "scan_wrapper_depth_convergence_patch":
            module.audit = lambda: (True, "depth=2;max=8;cycle=False")
        elif module_name == "bot.okx_regional_endpoint_isolation_patch":
            module.resolve_okx_base_url = lambda: "https://us.okx.com"
        elif module_name == "bot.account_scope_exit_integrity_final_patch":
            module.installed_marker = lambda: "20260718-account-scope-exit-integrity"
        elif module_name == "bot.downstream_risk_governor_equity_repair_patch":
            module._MARKER = "20260714-downstream-risk-v2"

        modules[module_name] = module

    return modules, expected


def test_source_bootstrap_installs_current_guard_chain_in_order(monkeypatch):
    _reset_source_bootstrap(monkeypatch)
    calls: list[str] = []
    modules, expected = _fake_runtime_modules(calls)
    expected.insert(expected.index("downstream_risk"), "zero_signal_state")

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
    assert calls == expected
    assert calls.count("zero_signal_state") == 2
    assert calls.index("scan_depth") < calls.index("convergence")
    assert calls.index("scan_delegate") < calls.index("scan_clamp")
    assert calls.index("scan_owner") < calls.index("downstream_risk")
    assert calls.index("quiescence") < calls.index("post_import")
    assert source_bootstrap.installed_marker() == "20260718-live-state-bootstrap-v2"
    assert source_bootstrap.os.environ["NIJA_SCAN_WRAPPER_DEPTH_GUARD_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] == "1"
    assert source_bootstrap.os.environ["NIJA_ACCOUNT_SCOPE_EXIT_INTEGRITY_INSTALLED"] == "1"


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
    assert source_bootstrap.os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] == "0"
    assert source_bootstrap.os.environ["NIJA_RUNTIME_CONVERGENCE_QUIESCENCE_READY"] == "0"
    assert source_bootstrap.os.environ["NIJA_SCAN_WRAPPER_DEPTH_READY"] == "0"
    assert source_bootstrap.os.environ["NIJA_SOURCE_WRITER_AUTHORITY_INSTALLED"] == "0"


def test_global_startup_guards_install_source_repair_before_other_guards(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    path = root / "bot" / "global_runtime_startup_guards.py"
    spec = importlib.util.spec_from_file_location(
        "nija_test_global_runtime_startup_guards", path
    )
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
        lambda name: fake_source
        if name == "source_runtime_guard_bootstrap"
        else real_import(name),
    )
    monkeypatch.setattr(module, "_set_defaults", lambda: order.append("defaults"))
    monkeypatch.setattr(
        module, "_install_kraken_patch_log_dedupe", lambda: order.append("dedupe")
    )
    monkeypatch.setattr(
        module,
        "_install_module",
        lambda module_name, marker: order.append(module_name) or True,
    )
    monkeypatch.delattr(
        builtins, "_NIJA_GLOBAL_RUNTIME_STARTUP_GUARDS_20260706B", raising=False
    )

    module.install()

    assert order[0] == "source"
    assert order[1] == "defaults"
    assert "held_trade_cap_guard_patch" in order
