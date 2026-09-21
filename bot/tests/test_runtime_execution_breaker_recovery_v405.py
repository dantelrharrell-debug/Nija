from __future__ import annotations

import threading
from types import SimpleNamespace

from bot import runtime_execution_breaker_recovery_v405_patch as v405


def _fake_tsm(*, rejected_orders: int):
    return SimpleNamespace(
        _EXECUTION_CIRCUIT_BREAKER_TRIPPED=True,
        _EXECUTION_CIRCUIT_BREAKER_REASON=(
            "heartbeat_verification threshold=2 "
            "detail=verification_stale age_s=1803.6 max_age_s=1800.0"
        ),
        _EXECUTION_CIRCUIT_BREAKER_COUNTS={
            "heartbeat_verification": 2,
            "rejected_orders": rejected_orders,
        },
        _EXECUTION_CIRCUIT_BREAKER_LOCK=threading.RLock(),
        _execution_circuit_breaker_thresholds=lambda: {
            "heartbeat_verification": 2,
            "rejected_orders": 5,
        },
        _heartbeat_verification_status=lambda: (
            True,
            "",
            {
                "verification_source": "canonical_execution_marker_v402",
                "source": "canonical_confirmed_fill",
                "age_s": 1.0,
            },
        ),
        _runtime_writer_nonce_ready=lambda: (True, "strict_writer_nonce_ready"),
    )


def test_recovered_heartbeat_clears_latch_but_preserves_subthreshold_counts(monkeypatch):
    fake = _fake_tsm(rejected_orders=1)
    monkeypatch.setattr(v405, "_tsm", lambda: fake)
    monkeypatch.setattr(v405, "_kill_switch_clear", lambda: (True, "clear"))

    assert v405._clear_recovered_heartbeat_latch_once() is True
    assert fake._EXECUTION_CIRCUIT_BREAKER_TRIPPED is False
    assert fake._EXECUTION_CIRCUIT_BREAKER_REASON == ""
    assert fake._EXECUTION_CIRCUIT_BREAKER_COUNTS == {"rejected_orders": 1}


def test_recovered_heartbeat_does_not_clear_another_threshold_level_anomaly(monkeypatch):
    fake = _fake_tsm(rejected_orders=5)
    monkeypatch.setattr(v405, "_tsm", lambda: fake)
    monkeypatch.setattr(v405, "_kill_switch_clear", lambda: (True, "clear"))

    assert v405._clear_recovered_heartbeat_latch_once() is False
    assert fake._EXECUTION_CIRCUIT_BREAKER_TRIPPED is True
    assert fake._EXECUTION_CIRCUIT_BREAKER_COUNTS == {"rejected_orders": 5}
