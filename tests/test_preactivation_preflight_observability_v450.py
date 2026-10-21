"""Non-authorizing startup preflight diagnostic regression checks."""
import importlib.util
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1] / "preactivation_readiness_convergence_v16_patch.py"


def load():
    spec = importlib.util.spec_from_file_location("nija_v450_preflight_isolated", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def configure(monkeypatch, v16):
    monkeypatch.setattr(v16, "_capital_snapshot", lambda: {
        "hydrated": True, "stale": False, "real": 100.0, "registered": 3
    })
    monkeypatch.setattr(v16, "_strict_authority_ready", lambda: (True, "ok"))
    monkeypatch.setattr(v16, "_kill_switch_clear", lambda: (True, ""))
    monkeypatch.setattr(v16, "_bootstrap_ready", lambda: (True, []))
    monkeypatch.setattr(v16, "_strategy_published", lambda: True)
    monkeypatch.setattr(v16, "_execution_pipeline_ready", lambda: True)
    monkeypatch.setattr(v16, "_live_mode", lambda: True)
    for name in ("NIJA_PRE_DISPATCH_RISK_SIZING_READY",
                 "NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED",
                 "NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED"):
        monkeypatch.setenv(name, "1")


def test_idle_preflight_visibility_never_grants_execution(monkeypatch):
    v16 = load()
    configure(monkeypatch, v16)
    monkeypatch.setattr(v16, "_genuine_execution_marker_proof",
                        lambda: (False, "execution_marker_missing_future_or_stale"))
    proofs, details = v16._collect_proofs()
    assert details["preflight_operational_ready_observed"] is True
    assert details["preflight_is_authorization"] is False
    assert details["post_trade_execution_evidence_verified"] is False
    assert proofs["execution_ready"] is False


def test_kill_switch_or_missing_risk_also_blocks_preflight(monkeypatch):
    v16 = load()
    configure(monkeypatch, v16)
    monkeypatch.setattr(v16, "_genuine_execution_marker_proof",
                        lambda: (True, "fresh_genuine_order_or_fill_execution_proof"))
    monkeypatch.setattr(v16, "_kill_switch_clear", lambda: (False, "kill_switch_active"))
    proofs, details = v16._collect_proofs()
    assert details["preflight_operational_ready_observed"] is False
    assert "authority" in details["preflight_missing"]
    assert proofs["execution_ready"] is False
    monkeypatch.setattr(v16, "_kill_switch_clear", lambda: (True, ""))
    monkeypatch.setenv("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED", "0")
    proofs, details = v16._collect_proofs()
    assert details["preflight_operational_ready_observed"] is False
    assert "risk" in details["preflight_missing"]
    assert proofs["execution_ready"] is False


def test_stale_capital_blocks_preflight_even_with_fresh_execution_evidence(monkeypatch):
    v16 = load()
    configure(monkeypatch, v16)
    monkeypatch.setattr(v16, "_capital_snapshot", lambda: {
        "hydrated": True, "stale": True, "real": 100.0, "registered": 3
    })
    monkeypatch.setattr(v16, "_genuine_execution_marker_proof",
                        lambda: (True, "fresh_genuine_order_or_fill_execution_proof"))
    proofs, details = v16._collect_proofs()
    assert details["preflight_operational_ready_observed"] is False
    assert "capital" in details["preflight_missing"]
    assert proofs["capital_ready"] is False
    assert proofs["execution_ready"] is False


def test_missing_execution_evidence_cannot_be_replaced_by_preflight(monkeypatch):
    v16 = load()
    configure(monkeypatch, v16)
    monkeypatch.setattr(v16, "_genuine_execution_marker_proof",
                        lambda: (False, "verification_stale"))
    proofs, details = v16._collect_proofs()
    assert details["preflight_operational_ready_observed"] is True
    assert details["preflight_is_authorization"] is False
    assert details["post_trade_execution_evidence_verified"] is False
    assert proofs["execution_ready"] is False


def test_independent_pretrade_certificate_requires_every_literal_true(monkeypatch):
    from types import ModuleType
    v16 = load()
    name = "bot.pretrade_independent_attestation"
    module = ModuleType(name)
    fields = (
        "account_permissions", "account_identity", "broker_balances",
        "position_ledger_reconciliation", "protective_exit_readback",
        "open_order_reconciliation", "duplicate_order_fence",
        "writer_lease", "nonce_sequence", "operator_authorization",
    )
    module.current_authenticated_attestations = lambda account: {key: True for key in fields}
    monkeypatch.setitem(sys.modules, name, module)
    assert v16._independent_pretrade_certificate() == (True, [])
    module.current_authenticated_attestations = lambda account: {
        **{key: True for key in fields}, "protective_exit_readback": "true"
    }
    ok, missing = v16._independent_pretrade_certificate()
    assert not ok and missing == ["protective_exit_readback"]


def test_missing_independent_attestor_does_not_grant_authority(monkeypatch):
    v16 = load()
    configure(monkeypatch, v16)
    monkeypatch.setattr(v16, "_genuine_execution_marker_proof",
                        lambda: (False, "verification_stale"))
    monkeypatch.setattr(v16, "_independent_pretrade_certificate",
                        lambda: (False, ["position_ledger_reconciliation"]))
    proofs, details = v16._collect_proofs()
    assert details["independent_pretrade_certified"] is False
    assert details["independent_pretrade_is_authorization"] is False
    assert "position_ledger_reconciliation" in details["independent_pretrade_missing"]
    assert proofs["execution_ready"] is False


def test_authenticated_pretrade_producer_requires_scope_freshness_and_provenance():
    import importlib.util
    source = SOURCE.parents[0] / "bot" / "pretrade_independent_attestation.py"
    spec = importlib.util.spec_from_file_location("nija_attestor_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account = "platform:kraken"
    evidence = {
        "account": account, "source": "authenticated_independent",
        "observed_at_epoch": 1000.0, "read_only": True, "scope_verified": True,
        "checks": {field: True for field in module.FIELDS},
        "provenance": {
            "authenticated_broker_read_verified": True,
            "ledger_snapshot_verified": True,
            "complete_pagination_verified": True,
            "collector_identity_verified": True,
            "account_scope_verified": True,
        },
    }
    module.install_authenticated_collector(lambda _: evidence)
    assert all(module.current_authenticated_attestations(account, now=1001.0).values())
    assert not any(module.current_authenticated_attestations("platform:other", now=1001.0).values())
    assert not any(module.current_authenticated_attestations(account, now=1061.0).values())
    evidence["provenance"]["complete_pagination_verified"] = False
    assert not any(module.current_authenticated_attestations(account, now=1001.0).values())


def test_integrated_attestation_contract_is_fail_closed():
    import importlib.util
    source = SOURCE.parents[0] / "bot" / "pretrade_independent_attestation.py"
    spec = importlib.util.spec_from_file_location("nija_attestor_integrated", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account = "platform:kraken"
    assert not any(module.current_authenticated_attestations(account).values())
    evidence = {
        "account": account, "source": "authenticated_independent",
        "observed_at_epoch": 1000.0, "read_only": True, "scope_verified": True,
        "checks": {field: True for field in module.FIELDS},
        "provenance": {
            "authenticated_broker_read_verified": True,
            "ledger_snapshot_verified": True,
            "complete_pagination_verified": True,
            "collector_identity_verified": True,
            "account_scope_verified": True,
        },
    }
    module.install_authenticated_collector(lambda _: evidence)
    assert all(module.current_authenticated_attestations(account, now=1020.0).values())
    assert not any(module.current_authenticated_attestations("user:other:kraken", now=1020.0).values())
    assert not any(module.current_authenticated_attestations(account, now=1061.0).values())
    evidence["checks"]["protective_exit_readback"] = "true"
    assert module.current_authenticated_attestations(account, now=1020.0)["protective_exit_readback"] is False
    evidence["source"] = "local_cache"
    assert not any(module.current_authenticated_attestations(account, now=1020.0).values())


def test_adapter_requires_risk_and_kill_switch_evidence():
    import importlib.util
    source = SOURCE.parents[0] / "bot" / "preflight_observability.py"
    spec = importlib.util.spec_from_file_location("nija_preflight_adapter_integrated", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = {field: True for field in module.REQUIRED_PREFLIGHT}
    assert all(module.certificate_from_independent_evidence(evidence).values())
    evidence["kill_switch_clear"] = False
    assert not any(module.certificate_from_independent_evidence(evidence).values())
def test_certificate_adapter_requires_literal_true_and_never_authorizes():
    import importlib.util
    source = SOURCE.parents[0] / "bot" / "preflight_observability.py"
    spec = importlib.util.spec_from_file_location("nija_preflight_adapter", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = {field: True for field in module.REQUIRED_PREFLIGHT}
    result = module.certificate_from_independent_evidence(evidence)
    assert all(result.values())
    evidence["protective_exits_verified"] = "true"
    result = module.certificate_from_independent_evidence(evidence)
    assert result["protective_exit_readback"] is False
    assert module.observe_preflight(evidence)["activation_allowed"] is False
