from __future__ import annotations

import bot.runtime_release_manifest_patch as manifest


def _clear(monkeypatch):
    for name in (
        "NIJA_SECONDARY_VENUE_POLICY",
        "NIJA_REQUIRED_VENUES_MISSING",
        "NIJA_REQUIRED_VENUES_READY",
        "NIJA_GLOBAL_TRADING_READY",
        "NIJA_MULTI_BROKER_TRADING_READY",
        "NIJA_ACTIVE_LIVE_VENUES",
        "NIJA_ZERO_SIGNAL_STREAK_CAP",
        "NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)


def test_v10_release_id():
    assert manifest.RELEASE_ID == "20260714-runtime-convergence-v10"


def test_v10_requires_module_identity_and_fail_closed_risk_flags():
    assert manifest._REQUIRED_FLAGS["module_identity_guard"] == "NIJA_RUNTIME_MODULE_IDENTITY_GUARD_INSTALLED"
    assert manifest._REQUIRED_FLAGS["module_identity_ready"] == "NIJA_RUNTIME_MODULE_IDENTITY_READY"
    assert manifest._REQUIRED_FLAGS["core_loop_limits"] == "NIJA_CORE_LOOP_PROGRESS_LIMITS_NORMALIZED"
    assert manifest._REQUIRED_FLAGS["downstream_risk_v2_installed"] == "NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED"
    assert manifest._REQUIRED_FLAGS["pre_dispatch_risk_fail_closed"] == "NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED"
    assert manifest._REQUIRED_FLAGS["pre_dispatch_risk_ready"] == "NIJA_PRE_DISPATCH_RISK_SIZING_READY"


def test_runtime_limits_reject_streak_999_and_30_second_stall(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "999")
    monkeypatch.setenv("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S", "30")

    ok, reason = manifest._runtime_limits_consistent()

    assert ok is False
    assert "zero_signal_streak_cap=999" in reason
    assert "run_cycle_stall_warn_s=30.0" in reason


def test_runtime_limits_accept_bounded_streak_and_scan_appropriate_timeout(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")
    monkeypatch.setenv("NIJA_RUN_CYCLE_PHASE3_TIMEOUT_S", "120")

    ok, reason = manifest._runtime_limits_consistent()

    assert ok is True
    assert "zero_signal_streak_cap=12" in reason


def test_contract_accepts_broker_local_kraken_with_missing_secondaries(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NIJA_SECONDARY_VENUE_POLICY", "broker_local")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_MISSING", "coinbase,okx")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "0")
    monkeypatch.setenv("NIJA_GLOBAL_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_ACTIVE_LIVE_VENUES", "kraken")

    ok, reason = manifest._readiness_contract_consistent()

    assert ok is True
    assert "policy=broker_local" in reason
    assert "required_ready=0" in reason
    assert "global_ready=1" in reason
    assert "active=kraken" in reason


def test_contract_rejects_missing_required_venues_marked_ready(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NIJA_SECONDARY_VENUE_POLICY", "broker_local")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_MISSING", "coinbase,okx")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "1")
    monkeypatch.setenv("NIJA_GLOBAL_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_ACTIVE_LIVE_VENUES", "kraken")

    ok, reason = manifest._readiness_contract_consistent()

    assert ok is False
    assert reason.startswith("contradiction:missing=")


def test_contract_rejects_global_ready_without_active_venue(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("NIJA_SECONDARY_VENUE_POLICY", "broker_local")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_MISSING", "coinbase,okx")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "0")
    monkeypatch.setenv("NIJA_GLOBAL_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_ACTIVE_LIVE_VENUES", "")

    ok, reason = manifest._readiness_contract_consistent()

    assert ok is False
    assert reason == "contradiction:global_ready=1;active_live_venues=missing"
