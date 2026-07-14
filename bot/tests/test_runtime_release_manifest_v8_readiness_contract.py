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
    ):
        monkeypatch.delenv(name, raising=False)


def test_v9_release_id():
    assert manifest.RELEASE_ID == "20260714-runtime-convergence-v9"


def test_v9_requires_fail_closed_risk_sizing_flags():
    assert manifest._REQUIRED_FLAGS["downstream_risk_v2_installed"] == "NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED"
    assert manifest._REQUIRED_FLAGS["pre_dispatch_risk_fail_closed"] == "NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED"
    assert manifest._REQUIRED_FLAGS["pre_dispatch_risk_ready"] == "NIJA_PRE_DISPATCH_RISK_SIZING_READY"


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
