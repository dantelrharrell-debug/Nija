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
