from __future__ import annotations

import json
import time

import render_liveness_server as server
import render_readiness_state_bridge as bridge


def _reset(monkeypatch, tmp_path):
    state_file = tmp_path / "readiness.json"
    monkeypatch.setenv("NIJA_RENDER_READINESS_STATE_FILE", str(state_file))
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_NAME", raising=False)
    monkeypatch.delenv("RENDER_INSTANCE_ID", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
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
        "NIJA_COINBASE_SPENDABLE_QUOTE",
        "NIJA_OKX_ACTIVATION_STATE",
        "NIJA_OKX_CONNECTED",
        "NIJA_OKX_TRADING_READY",
        "NIJA_OKX_SPENDABLE_QUOTE",
    ):
        monkeypatch.delenv(name, raising=False)
    return state_file


def test_readiness_is_false_until_required_venues_are_ready(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "0")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_MISSING", "coinbase,okx")

    ready, details = server._readiness()

    assert ready is False
    assert details["status"] == "not_ready"
    assert details["required_venues_missing"] == "coinbase,okx"
    assert details["readiness_source"] == "process_env"


def test_readiness_requires_live_state_and_writer_authority(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
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


def test_readiness_passes_with_live_authority_and_both_venues(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
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


def test_bridge_file_overrides_stale_liveness_process_environment(monkeypatch, tmp_path):
    state_file = _reset(monkeypatch, tmp_path)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "1")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_MISSING", "")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "ready")
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_OKX_ACTIVATION_STATE", "ready")
    monkeypatch.setenv("NIJA_OKX_CONNECTED", "1")
    monkeypatch.setenv("NIJA_OKX_TRADING_READY", "1")

    bridge.publish_once()

    # Simulate the separate HTTP process retaining its old startup environment.
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "OFF")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "0")

    ready, details = server._readiness()

    assert state_file.is_file()
    assert ready is True
    assert details["readiness_source"] == "shared_file"
    assert details["state"] == "LIVE_ACTIVE"
    assert details["writer_authority"] == "1"


def test_render_without_fresh_shared_state_is_safely_not_ready(monkeypatch, tmp_path):
    state_file = _reset(monkeypatch, tmp_path)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_REQUIRED_VENUES_READY", "1")

    state_file.write_text(
        json.dumps(
            {
                "timestamp": time.time() - 120,
                "state": "LIVE_ACTIVE",
                "writer_authority": "1",
                "strict_secondary_venues": "true",
                "required_venues_ready": "1",
            }
        ),
        encoding="utf-8",
    )

    ready, details = server._readiness()

    assert ready is False
    assert details["readiness_source"] == "safe_render_startup"
    assert details["shared_state_status"] == "stale"
