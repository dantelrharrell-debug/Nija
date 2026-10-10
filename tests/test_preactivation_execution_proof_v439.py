"""Regression: no LIVE_ACTIVE permission before genuine execution proof."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "preactivation_readiness_convergence_v16_patch.py"


def load():
    name = "test_pre_activation_provenance_v439_isolated"
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_verifier_fails_closed(monkeypatch):
    v16 = load()
    # Other CI tests import bot.trading_state_machine during collection. Clear
    # that cached module so this test actually exercises the absent-verifier
    # startup branch rather than a preloaded verifier with a missing marker.
    monkeypatch.delitem(sys.modules, "bot.trading_state_machine", raising=False)
    monkeypatch.setattr(v16.importlib, "import_module", lambda n: ModuleType(n))
    ok, detail = v16._genuine_execution_marker_proof()
    assert not ok
    assert "unavailable" in detail


def test_stale_and_auth_only_never_authorize(monkeypatch):
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    valid = dict(stage="ORDER_VERIFY", source="heartbeat_trade",
                 proof_kind="execution_probe", verified_at_epoch=9999)
    for meta in (
        {**valid, "stage": "AUTH_VERIFY"},
        {**valid, "source": "authority_heartbeat"},
        {**valid, "proof_kind": "authority_liveness"},
        {**valid, "verified_at_epoch": 8000},
        {**valid, "verified_at_epoch": 10030},
        {**valid, "verified_at_epoch": 0},
    ):
        tsm._heartbeat_verification_status = lambda m=meta: (True, "", m)
        ok, _ = v16._genuine_execution_marker_proof()
        assert ok is False
    tsm._heartbeat_verification_status = lambda: (False, "marker_missing", {})
    assert v16._genuine_execution_marker_proof()[0] is False


def test_fresh_verified_order_proof_is_accepted(monkeypatch):
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    tsm._heartbeat_verification_status = lambda: (
        True, "", {"stage": "ORDER_VERIFY", "source": "heartbeat_trade",
                    "proof_kind": "execution_probe", "verified_at_epoch": 9990}
    )
    assert v16._genuine_execution_marker_proof()[0] is True


def test_collector_never_marks_execution_ready_without_proof(monkeypatch):
    v16 = load()
    monkeypatch.setattr(v16, "_capital_snapshot", lambda: {
        "hydrated": True, "stale": False, "real": 100.0, "registered": 3})
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
    monkeypatch.setattr(v16, "_genuine_execution_marker_proof",
                        lambda: (False, "verification_stale"))
    proofs, details = v16._collect_proofs()
    assert proofs["authority_ready"] is True
    assert proofs["nonce_ready"] is True
    assert proofs["risk_ready"] is True
    assert proofs["execution_ready"] is False
    assert details["execution_marker_detail"] == "verification_stale"


def test_fresh_canonical_confirmed_fill_requires_independent_provenance(monkeypatch):
    """A genuine canonical fill is eligible only after both verifiers agree."""
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", "1")
    marker = dict(
        stage="FILL_VERIFY", source="canonical_confirmed_fill",
        proof_kind="execution_probe", verified_at_epoch=9990,
    )
    tsm._heartbeat_verification_status = lambda: (True, "", dict(marker))
    tsm._canonical_execution_verification_status_v402 = lambda: (
        True, "", dict(marker)
    )
    assert v16._genuine_execution_marker_proof() == (
        True, "fresh_genuine_order_or_fill_execution_proof"
    )


def test_canonical_fill_proof_rejects_missing_provenance_guard_and_verifier(monkeypatch):
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    marker = dict(
        stage="FILL_VERIFY", source="canonical_confirmed_fill",
        proof_kind="execution_probe", verified_at_epoch=9990,
    )
    tsm._heartbeat_verification_status = lambda: (True, "", dict(marker))
    monkeypatch.delenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", raising=False)
    assert v16._genuine_execution_marker_proof()[0] is False
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", "1")
    assert v16._genuine_execution_marker_proof()[0] is False


def test_canonical_fill_proof_rejects_unverified_stage_scope_and_time(monkeypatch):
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", "1")
    good = dict(
        stage="FILL_VERIFY", source="canonical_confirmed_fill",
        proof_kind="execution_probe", verified_at_epoch=9990,
    )
    tsm._heartbeat_verification_status = lambda: (True, "", dict(good))
    for second in (
        (False, "v169_provenance_rejected", dict(good)),
        (True, "", {**good, "stage": "AUTH_VERIFY"}),
        (True, "", {**good, "source": "authority_heartbeat"}),
        (True, "", {**good, "proof_kind": "authority_liveness"}),
        (True, "", {**good, "verified_at_epoch": 9991}),
    ):
        tsm._canonical_execution_verification_status_v402 = lambda value=second: value
        assert v16._genuine_execution_marker_proof()[0] is False
    tsm._canonical_execution_verification_status_v402 = lambda: (True, "", dict(good))
    for bad in (
        {**good, "stage": "ORDER_VERIFY"},
        {**good, "verified_at_epoch": 7000},
        {**good, "verified_at_epoch": 10030},
        {**good, "proof_kind": "authority_liveness"},
        {**good, "source": "unrecognized"},
    ):
        tsm._heartbeat_verification_status = lambda marker=bad: (True, "", marker)
        assert v16._genuine_execution_marker_proof()[0] is False


def test_canonical_fill_does_not_mark_execution_ready_without_real_proof(monkeypatch):
    """Positive integration is strictly conditional on a fresh matching canonical verifier."""
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", "1")
    marker = dict(
        stage="FILL_VERIFY", source="canonical_confirmed_fill",
        proof_kind="execution_probe", verified_at_epoch=6000,
    )
    tsm._heartbeat_verification_status = lambda: (True, "", dict(marker))
    tsm._canonical_execution_verification_status_v402 = lambda: (True, "", dict(marker))
    assert v16._genuine_execution_marker_proof()[0] is False
