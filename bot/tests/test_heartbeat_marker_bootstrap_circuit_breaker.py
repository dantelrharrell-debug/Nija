"""Regression coverage for pre-proof heartbeat circuit-breaker behavior."""
from __future__ import annotations

from unittest.mock import patch

from bot import trading_state_machine as tsm


def test_missing_bootstrap_marker_fails_closed_without_tripping_breaker() -> None:
    with patch.object(tsm, "_heartbeat_verification_required", return_value=True), patch.object(
        tsm,
        "_heartbeat_verification_status",
        return_value=(False, "marker_missing", {}),
    ), patch.object(tsm, "_record_execution_anomaly") as record:
        ready, reason = tsm._runtime_writer_nonce_ready()

    assert ready is False
    assert reason == "heartbeat_verification:marker_missing"
    record.assert_not_called()


def test_invalid_existing_marker_remains_circuit_breaker_anomaly() -> None:
    with patch.object(tsm, "_heartbeat_verification_required", return_value=True), patch.object(
        tsm,
        "_heartbeat_verification_status",
        return_value=(False, "marker_malformed:bad-json", {}),
    ), patch.object(tsm, "_record_execution_anomaly") as record:
        ready, reason = tsm._runtime_writer_nonce_ready()

    assert ready is False
    assert reason == "heartbeat_verification:marker_malformed:bad-json"
    record.assert_called_once_with("heartbeat_verification", "marker_malformed:bad-json")
