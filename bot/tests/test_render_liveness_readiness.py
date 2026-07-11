from __future__ import annotations

import render_liveness_server as server


def _reset(monkeypatch):
    for name in (
        "NIJA_RUNTIME_TRADING_STATE",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        "NIJA_REQUIRE_SECONDARY_VENUES_READY",
        "NIJA_REQUIRED_VENUES_READY",
        "NIJA_REQUIRED_LIVE_VENUES",
        "NIJA_REQUIRED_VENUES_MISSING",
        "NIJA_COINBASE_ACTIVATION_STATE",
        "NIJA_COINBASE_CONNECTED",
        "NIJA_COINBASE_TRADING_READY",
        "NIJA_OKX_ACTIVATION_STATE",
        "NIJA_OKX_CONNECTED",
        "NIJA_OKX_TRADING_READY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_readiness_is_false_until_required_venues_are_ready(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "0")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_MISSING", "coinbase,okx")

    ready, details = server._readiness()

    assert ready is False
    assert details["status"] == "not_ready"
    assert details["required_venues_missing"] == "coinbase,okx"


def test_readiness_requires_live_state_and_writer_authority(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "1")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_PENDING_CONFIRMATION")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")

    ready, _details = server._readiness()
    assert ready is False

    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    ready, _details = server._readiness()
    assert ready is False


def test_readiness_passes_with_live_authority_and_both_venues(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "1")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "ready")
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_OKX_ACTIVATION_STATE", "ready")
    monkeypatch.setenv("NIJA_OKX_CONNECTED", "1")
    monkeypatch.setenv("NIJA_OKX_TRADING_READY", "1")

    ready, details = server._readiness()

    assert ready is True
    assert details["status"] == "ready"
    assert details["coinbase_trading_ready"] == "1"
    assert details["okx_trading_ready"] == "1"
