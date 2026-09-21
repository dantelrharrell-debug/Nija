"""Regression coverage for canonical heartbeat freshness hardening v424."""

from bot import trading_state_machine as tsm


def _happy_runtime(monkeypatch):
    monkeypatch.setattr(tsm, "_heartbeat_verification_required", lambda: True)
    monkeypatch.setattr(tsm, "_distributed_writer_authority_gate", lambda: (True, ""))
    monkeypatch.setattr(tsm, "_writer_heartbeat_gate", lambda: (True, ""))
    monkeypatch.setattr(tsm, "_nonce_sync_gate", lambda: (True, ""))
    monkeypatch.setattr(tsm, "_nonce_writer_lease_gate", lambda: (True, ""))
    monkeypatch.setattr(tsm, "_writer_lease_generation_gate", lambda: (True, ""))


def test_stale_primary_with_fresh_canonical_proof_does_not_trip_anomaly(monkeypatch):
    _happy_runtime(monkeypatch)
    monkeypatch.setattr(
        tsm,
        "_heartbeat_verification_status",
        lambda: (
            False,
            "verification_stale age_s=1803.8 max_age_s=1800.0",
            {"age_s": 1803.8, "max_age_s": 1800.0},
        ),
    )
    monkeypatch.setattr(
        tsm,
        "_canonical_execution_verification_status_v402",
        lambda: (
            True,
            "",
            {
                "source": "canonical_confirmed_fill",
                "age_s": 1009.4,
                "max_age_s": 1800.0,
                "verification_source": "canonical_execution_marker_v402",
            },
        ),
        raising=False,
    )
    anomalies = []
    monkeypatch.setattr(
        tsm,
        "_record_execution_anomaly",
        lambda kind, detail="": anomalies.append((kind, detail)),
    )

    assert tsm._runtime_writer_nonce_ready() == (True, "")
    assert anomalies == []


def test_stale_primary_stays_fail_closed_when_canonical_proof_is_not_ready(monkeypatch):
    _happy_runtime(monkeypatch)
    stale = "verification_stale age_s=1803.8 max_age_s=1800.0"
    monkeypatch.setattr(
        tsm,
        "_heartbeat_verification_status",
        lambda: (False, stale, {"age_s": 1803.8, "max_age_s": 1800.0}),
    )
    monkeypatch.setattr(
        tsm,
        "_canonical_execution_verification_status_v402",
        lambda: (
            False,
            "canonical_execution_verification_stale_v402 age_s=1803.8 max_age_s=1800.0",
            {},
        ),
        raising=False,
    )
    anomalies = []
    monkeypatch.setattr(
        tsm,
        "_record_execution_anomaly",
        lambda kind, detail="": anomalies.append((kind, detail)),
    )

    ready, reason = tsm._runtime_writer_nonce_ready()
    assert ready is False
    assert reason == f"heartbeat_verification:{stale}"
    assert anomalies == [("heartbeat_verification", stale)]


def test_malformed_primary_never_uses_stale_primary_exception(monkeypatch):
    _happy_runtime(monkeypatch)
    monkeypatch.setattr(
        tsm,
        "_heartbeat_verification_status",
        lambda: (False, "marker_malformed:test", {}),
    )
    canonical_calls = []
    monkeypatch.setattr(
        tsm,
        "_canonical_execution_verification_status_v402",
        lambda: canonical_calls.append(True) or (True, "", {}),
        raising=False,
    )
    anomalies = []
    monkeypatch.setattr(
        tsm,
        "_record_execution_anomaly",
        lambda kind, detail="": anomalies.append((kind, detail)),
    )

    ready, reason = tsm._runtime_writer_nonce_ready()
    assert ready is False
    assert reason == "heartbeat_verification:marker_malformed:test"
    assert canonical_calls == []
    assert anomalies == [("heartbeat_verification", "marker_malformed:test")]
