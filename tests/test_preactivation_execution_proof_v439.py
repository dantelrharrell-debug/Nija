"""Regression: no LIVE_ACTIVE permission before genuine execution proof."""
from __future__ import annotations

import importlib.util
import json
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
                 proof_kind="execution_probe", verified_at_epoch=9999,
                 broker_event_at_epoch=9999)
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
                    "proof_kind": "execution_probe", "verified_at_epoch": 9990,
                    "broker_event_at_epoch": 9990}
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
        required_stage="FILL_VERIFY", proof_kind="execution_probe", verified_at_epoch=9990,
        broker_event_at_epoch=9990,
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
        required_stage="FILL_VERIFY", proof_kind="execution_probe", verified_at_epoch=9990,
        broker_event_at_epoch=9990,
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
        required_stage="FILL_VERIFY", proof_kind="execution_probe", verified_at_epoch=9990,
        broker_event_at_epoch=9990,
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
        required_stage="FILL_VERIFY", proof_kind="execution_probe", verified_at_epoch=6000,
        broker_event_at_epoch=6000,
    )
    tsm._heartbeat_verification_status = lambda: (True, "", dict(marker))
    tsm._canonical_execution_verification_status_v402 = lambda: (True, "", dict(marker))
    assert v16._genuine_execution_marker_proof()[0] is False


def test_canonical_fill_rejects_auth_only_or_missing_execution_policy(monkeypatch):
    """A FILL_VERIFY label must not upgrade an AUTH_VERIFY policy into execution proof."""
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", "1")
    marker = dict(
        stage="FILL_VERIFY", source="canonical_confirmed_fill",
        proof_kind="execution_probe", verified_at_epoch=9990,
        broker_event_at_epoch=9990,
    )
    tsm._heartbeat_verification_status = lambda: (True, "", dict(marker))
    for policy in (None, "", "AUTH_VERIFY", "AUTH_ONLY", "unknown", False, 1):
        canonical = {**marker, "required_stage": policy}
        tsm._canonical_execution_verification_status_v402 = lambda value=canonical: (
            True, "auth_only_policy", dict(value)
        )
        assert v16._genuine_execution_marker_proof() == (
            False, "canonical_proof_execution_policy_unverified"
        )


def test_canonical_fill_requires_execution_policy_and_unchanged_freshness(monkeypatch):
    """Both execution policies preserve stale/future and provenance denials."""
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", "1")
    for policy in ("ORDER_VERIFY", "FILL_VERIFY"):
        for epoch, expected in ((9990, True), (8200, True), (8199, False), (10006, False)):
            marker = dict(
                stage="FILL_VERIFY", source="canonical_confirmed_fill",
                proof_kind="execution_probe", verified_at_epoch=epoch,
                broker_event_at_epoch=epoch,
                required_stage=policy,
            )
            tsm._heartbeat_verification_status = lambda value=marker: (True, "", dict(value))
            tsm._canonical_execution_verification_status_v402 = lambda value=marker: (
                True, "", dict(value)
            )
            assert v16._genuine_execution_marker_proof()[0] is expected
            tsm._canonical_execution_verification_status_v402 = lambda value=marker: (
                False, "v169_provenance_rejected", dict(value)
            )
            assert v16._genuine_execution_marker_proof()[0] is False



def test_recent_verification_cannot_refresh_old_broker_event(monkeypatch, caplog):
    import logging
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000.0)
    base = {
        "stage": "ORDER_VERIFY",
        "source": "heartbeat_trade",
        "proof_kind": "execution_probe",
        "verified_at_epoch": 9999.0,
    }
    for event, expected in (
        (None, "broker_execution_event_missing_future_or_stale"),
        (8199.0, "broker_execution_event_missing_future_or_stale"),
        (10006.0, "broker_execution_event_missing_future_or_stale"),
        (10005.0, "broker_execution_event_after_verification"),
        (float("nan"), "broker_execution_event_missing_future_or_stale"),
        (True, "broker_execution_event_missing_future_or_stale"),
    ):
        marker = dict(base)
        if event is not None:
            marker["broker_event_at_epoch"] = event
        tsm._heartbeat_verification_status = lambda m=marker: (True, "", dict(m))
        with caplog.at_level(logging.WARNING, logger="nija.preactivation_readiness_convergence_v16"):
            allowed, reason = v16._genuine_execution_marker_proof()
        assert allowed is False
        assert reason == expected
    # The broker event age, not the recent verification age, is observable.
    assert "broker_event_age_s=" in caplog.text
    assert "verification_age_s=" in caplog.text


def test_real_broker_event_1800_second_limit_is_inclusive(monkeypatch):
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000.0)
    for epoch, allowed in ((8200.0, True), (8199.999, False)):
        payload = dict(stage="ORDER_VERIFY", source="heartbeat_trade",
                       proof_kind="execution_probe", verified_at_epoch=9990.0,
                       broker_event_at_epoch=epoch)
        tsm._heartbeat_verification_status = lambda m=payload: (True, "", dict(m))
        assert v16._genuine_execution_marker_proof()[0] is allowed


def test_canonical_verifiers_must_agree_on_broker_event_time(monkeypatch):
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    monkeypatch.setattr(v16.time, "time", lambda: 10000.0)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY", "1")
    marker = dict(stage="FILL_VERIFY", source="canonical_confirmed_fill",
                  required_stage="FILL_VERIFY", proof_kind="execution_probe",
                  verified_at_epoch=9990.0, broker_event_at_epoch=9989.0)
    tsm._heartbeat_verification_status = lambda: (True, "", dict(marker))
    tsm._canonical_execution_verification_status_v402 = lambda: (
        True, "", {**marker, "broker_event_at_epoch": 9988.0}
    )
    assert v16._genuine_execution_marker_proof() == (
        False, "canonical_broker_event_identity_mismatch"
    )
    tsm._canonical_execution_verification_status_v402 = lambda: (
        True, "", dict(marker)
    )
    assert v16._genuine_execution_marker_proof()[0] is True

def test_heartbeat_marker_rejects_future_and_stale_proofs_with_provenance(tmp_path, monkeypatch):
    from bot import startup_verification_evidence, trading_state_machine

    marker = tmp_path / "execution-proof.json"
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(marker))
    monkeypatch.setenv("HEARTBEAT_VERIFICATION_REQUIRED_STAGE", "FILL_VERIFY")
    monkeypatch.setenv("HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS", "1800")
    monkeypatch.setattr(
        startup_verification_evidence,
        "startup_attempts_allow_execution_proof",
        lambda: True,
    )
    monkeypatch.setattr(trading_state_machine.time, "time", lambda: 10000.0)
    payload = {
        "stage": "FILL_VERIFY",
        "source": "canonical_confirmed_fill",
        "proof_kind": "execution_probe",
        "producer": "test-fill-writer",
        "verified_at_epoch": 10006.0,
        "broker_event_at_epoch": 10006.0,
    }
    marker.write_text(json.dumps(payload), encoding="utf-8")

    ready, detail, metadata = trading_state_machine._heartbeat_verification_status()
    assert ready is False
    assert "future" in detail
    assert metadata["failure_condition"] == "verification_future"
    assert metadata["age_s"] == -6.0
    assert metadata["producer"] == "test-fill-writer"
    assert metadata["broker_event_at_epoch"] == 10006.0

    payload["verified_at_epoch"] = 8199.0
    marker.write_text(json.dumps(payload), encoding="utf-8")
    ready, detail, metadata = trading_state_machine._heartbeat_verification_status()
    assert ready is False
    assert "stale" in detail
    assert metadata["failure_condition"] == "verification_stale"
    assert metadata["age_s"] == 1801.0

    payload.pop("verified_at_epoch")
    marker.write_text(json.dumps(payload), encoding="utf-8")
    ready, detail, metadata = trading_state_machine._heartbeat_verification_status()
    assert ready is False
    assert detail == "marker_missing_timestamp"
    assert metadata["producer"] == "test-fill-writer"
    assert metadata["failure_condition"] == "marker_missing_timestamp"


def test_missing_heartbeat_marker_fails_closed(tmp_path, monkeypatch):
    from bot import startup_verification_evidence, trading_state_machine

    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(
        startup_verification_evidence,
        "startup_attempts_allow_execution_proof",
        lambda: True,
    )
    ready, detail, _ = trading_state_machine._heartbeat_verification_status()
    assert ready is False
    assert detail == "marker_missing"


def test_preactivation_logs_proof_producer_and_failure_condition(monkeypatch, caplog):
    v16 = load()
    tsm = ModuleType("bot.trading_state_machine")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", tsm)
    tsm._heartbeat_verification_status = lambda: (
        False,
        "verification_stale",
        {
            "source": "canonical_confirmed_fill",
            "stage": "FILL_VERIFY",
            "producer": "fill-writer-v346",
            "verified_at_epoch": 9000.0,
            "broker_event_at_epoch": 9000.0,
        },
    )
    monkeypatch.setattr(v16.time, "time", lambda: 10000.0)

    ready, detail = v16._genuine_execution_marker_proof()

    assert ready is False
    assert detail == "execution_marker:verification_stale"
    assert "source=canonical_confirmed_fill" in caplog.text
    assert "stage=FILL_VERIFY" in caplog.text
    assert "producer=fill-writer-v346" in caplog.text
    assert "broker_event_at_epoch=9000.000000" in caplog.text
    assert "verification_age_s=1000.0" in caplog.text
    assert "failing_condition=execution_marker" in caplog.text
