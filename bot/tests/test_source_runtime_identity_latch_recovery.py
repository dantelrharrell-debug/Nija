from __future__ import annotations

import os

import source_runtime_guard_bootstrap as bootstrap


def _healthy_details():
    return {
        "bot.downstream_risk_governor_equity_repair_patch": (
            "same_object=true;marker=20260714-downstream-risk-v2"
        ),
        "downstream_risk_module": (
            "same=True;marker=20260714-downstream-risk-v2"
        ),
        "execution_pipeline_chain": (
            "v2=True;legacy=False;cycle=False;depth=7"
        ),
        "zero_signal_streak_chain": (
            "cap_guard=True;state_repair=True;cycle=False;depth=27"
        ),
    }


def test_critical_identity_invariants_accept_exact_render_state():
    ready, reason = bootstrap._critical_identity_invariants(_healthy_details())

    assert ready is True
    assert reason == "all_critical_invariants_ready"


def test_critical_identity_invariants_reject_reported_duplicate():
    details = _healthy_details()
    details["bot.some_patch"] = "same_object=true;marker=x;duplicate=true"

    ready, reason = bootstrap._critical_identity_invariants(details)

    assert ready is False
    assert "no_reported_duplicates" in reason


def test_critical_identity_invariants_reject_legacy_wrapper():
    details = _healthy_details()
    details["execution_pipeline_chain"] = (
        "v2=True;legacy=True;cycle=False;depth=8"
    )

    ready, reason = bootstrap._critical_identity_invariants(details)

    assert ready is False
    assert "pipeline_no_legacy" in reason


def test_critical_identity_invariants_reject_cycle():
    details = _healthy_details()
    details["zero_signal_streak_chain"] = (
        "cap_guard=True;state_repair=True;cycle=True;depth=27"
    )

    ready, reason = bootstrap._critical_identity_invariants(details)

    assert ready is False
    assert "streak_no_cycle" in reason


def test_stale_latch_can_be_cleared_only_after_safe_first_audit(monkeypatch):
    details = _healthy_details()
    audits = iter(((False, details), (True, details)))

    class Identity:
        @staticmethod
        def audit():
            return next(audits)

    modules = {}
    required = (
        "prebot_writer_authority_fail_closed",
        "runtime_module_identity_convergence_patch",
        "writer_generation_scope_repair_patch",
        "authority_heartbeat_generation_scope_patch",
        "final_worker_position_coinbase_repair_patch",
        "broker_auth_recovery_patch",
        "runtime_convergence_hardening_patch",
        "bot.zero_signal_streak_state_repair_patch",
        "runtime_convergence_v2_patch",
        "runtime_auth_recursion_endpoint_repair_patch",
        "final_runtime_convergence_patch",
        "scan_wrapper_convergence_repair_patch",
        "venue_readiness_execution_repair_patch",
        "secondary_venue_activation_patch",
        "secondary_venue_strict_readiness_patch",
        "broker_local_readiness_contract_patch",
        "account_exit_management_recovery_patch",
        "account_exit_recovery_bootstrap_patch",
        "three_venue_execution_readiness",
        "render_readiness_state_bridge",
        "scan_owner_okx_auth_convergence_patch",
    )

    for name in required:
        if name == "runtime_module_identity_convergence_patch":
            modules[name] = Identity()
        else:
            modules[name] = type("M", (), {"install": staticmethod(lambda: None)})()

    monkeypatch.setattr(bootstrap, "_INSTALLED", False)
    monkeypatch.setattr(
        bootstrap.importlib,
        "import_module",
        lambda name: modules[name],
    )
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_DUPLICATE_PATCH_MODULE_DETECTED", "1")

    assert bootstrap.install() is True
    assert os.environ["NIJA_DUPLICATE_PATCH_MODULE_DETECTED"] == "0"
    assert os.environ["NIJA_RUNTIME_MODULE_IDENTITY_READY"] == "1"
