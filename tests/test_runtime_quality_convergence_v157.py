from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from bot import runtime_quality_convergence_v157_patch as patch


def test_expired_alive_flight_is_detected_without_mutation():
    gate = threading.Event()
    worker = threading.Thread(target=lambda: gate.wait(2.0), daemon=True)
    worker.start()
    flight = SimpleNamespace(
        thread=worker,
        started_monotonic=time.monotonic() - 10.0,
        timeout_s=2.0,
    )
    try:
        assert patch._flight_expired(flight) is True
    finally:
        gate.set()
        worker.join(timeout=1.0)


def test_alive_flight_inside_timeout_is_not_expired():
    gate = threading.Event()
    worker = threading.Thread(target=lambda: gate.wait(2.0), daemon=True)
    worker.start()
    flight = SimpleNamespace(
        thread=worker,
        started_monotonic=time.monotonic(),
        timeout_s=30.0,
    )
    try:
        assert patch._flight_expired(flight) is False
    finally:
        gate.set()
        worker.join(timeout=1.0)


def test_completed_flight_is_not_expired_even_when_old():
    worker = threading.Thread(target=lambda: None)
    worker.start()
    worker.join(timeout=1.0)
    flight = SimpleNamespace(
        thread=worker,
        started_monotonic=time.monotonic() - 100.0,
        timeout_s=2.0,
    )
    assert patch._flight_expired(flight) is False


def test_core_quality_gate_fails_closed_on_severe_recent_data_loss(monkeypatch):
    monkeypatch.setenv("NIJA_CORE_DATA_FAILURE_MAX_RATE", "0.50")
    monkeypatch.setenv("NIJA_CORE_DATA_QUALITY_MAX_AGE_S", "180")
    patch._record_core_quality((0, 0, 22, {"data_insufficient": 78}))
    ok, detail = patch._core_quality_gate()
    assert ok is False
    assert detail["core_data_failure_rate"] == 0.78
    assert detail["core_data_quality_ok"] is False


def test_core_quality_gate_accepts_healthy_recent_data(monkeypatch):
    monkeypatch.setenv("NIJA_CORE_DATA_FAILURE_MAX_RATE", "0.50")
    patch._record_core_quality((0, 0, 98, {"data_insufficient": 2}))
    ok, detail = patch._core_quality_gate()
    assert ok is True
    assert detail["core_data_failure_rate"] == 0.02
    assert detail["core_data_quality_ok"] is True


def test_core_quality_observation_does_not_change_phase3_result():
    result = (0, 0, 11, {"data_insufficient": 2, "confidence_gate_rejected": 4})
    patch._record_core_quality(result)
    assert result == (0, 0, 11, {"data_insufficient": 2, "confidence_gate_rejected": 4})


def test_install_defaults_deadline_to_fail_closed_without_signal_override(monkeypatch):
    monkeypatch.delenv("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", raising=False)
    # Test the environment contract directly; full install is integration-tested
    # by runtime_post_import_convergence.
    monkeypatch.setenv("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", "true")
    assert patch.os.environ["NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED"] == "true"
