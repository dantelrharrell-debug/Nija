from __future__ import annotations

import sys
import types

import pytest

from bot import runtime_drawdown_stop_provenance_v414_patch as v414


def test_production_reason_reconstructs_original_peak() -> None:
    reason = "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=5.28%, equity=$247.54)"
    ok, drawdown_pct, stopped_equity, original_peak, detail = v414._original_drawdown_reference(reason)

    assert ok is True
    assert drawdown_pct == pytest.approx(5.28)
    assert stopped_equity == pytest.approx(247.54)
    assert original_peak == pytest.approx(247.54 / (1.0 - 0.0528), rel=1e-9)
    assert original_peak == pytest.approx(261.34, abs=0.02)
    assert detail == "derived_peak_from_stop"


def test_explicit_peak_is_preserved() -> None:
    reason = "GlobalDrawdownCircuitBreaker: HALT (drawdown=7.33%, equity=$156.46, peak=$168.84)"
    ok, drawdown_pct, stopped_equity, original_peak, detail = v414._original_drawdown_reference(reason)

    assert ok is True
    assert drawdown_pct == pytest.approx(7.33)
    assert stopped_equity == pytest.approx(156.46)
    assert original_peak == pytest.approx(168.84)
    assert detail == "explicit_peak"


def test_exact_drawdown_source_rejects_restart_file_record() -> None:
    reason = "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=5.28%, equity=$247.54)"

    assert v414._exact_drawdown_source(reason, "GlobalDrawdownCircuitBreaker") is True
    assert v414._exact_drawdown_source("Kill switch file detected", "FILE_SYSTEM") is False
    assert v414._exact_drawdown_source(reason, "FILE_SYSTEM") is False
    assert v414._exact_drawdown_source("Daily loss limit exceeded", "AUTO_TRIGGER") is False


def test_causal_activation_prefers_v143_original_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("bot.kill_switch_persistence_provenance_v143_patch")
    fake._causal_activation_from_status = lambda status: (
        "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=5.28%, equity=$247.54)",
        "GlobalDrawdownCircuitBreaker",
    )
    monkeypatch.setitem(sys.modules, "bot.kill_switch_persistence_provenance_v143_patch", fake)

    status = {
        "recent_history": [
            {"reason": "Kill switch file detected", "source": "FILE_SYSTEM"},
        ]
    }
    reason, source = v414._causal_activation(status)

    assert source == "GlobalDrawdownCircuitBreaker"
    assert "drawdown=5.28%" in reason


def test_unparseable_or_impossible_reference_fails_closed() -> None:
    assert v414._original_drawdown_reference("Kill switch file detected")[0] is False
    assert v414._original_drawdown_reference(
        "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=100.00%, equity=$1.00)"
    )[0] is False


def test_oct6_legacy_replay_requires_exact_active_schema_v1_identity() -> None:
    legacy = {
        "is_active": True,
        "source": "FILE_SYSTEM",
        "reason": "Kill switch file detected",
        "timestamp": "2026-10-06T14:55:23.027303+00:00",
        "schema": 1,
    }
    assert v414._is_legacy_oct6_replay(legacy) is True
    assert v414._is_legacy_oct6_replay({**legacy, "schema": 2}) is False
    assert v414._is_legacy_oct6_replay({**legacy, "is_active": False}) is False
    assert v414._is_legacy_oct6_replay(
        {**legacy, "timestamp": "2026-10-06T14:55:23.027304+00:00"}
    ) is False


def test_oct6_migrated_identity_is_exact_and_immutable() -> None:
    migrated = {
        "is_active": True,
        "source": "FILE_SYSTEM",
        "reason": "Kill switch file detected",
        "timestamp": "2026-10-06T14:55:23.027303+00:00",
        "schema": 2,
        "origin_source": "GlobalDrawdownCircuitBreaker",
        "origin_reason": "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=20.31%, equity=$617.89)",
        "origin_timestamp": "2026-10-06T14:55:23.027303+00:00",
        "incident_id": v414._INCIDENT_20261006_ID,
    }
    assert v414._is_migrated_oct6_stop(migrated) is True
    assert v414._is_migrated_oct6_stop(
        {**migrated, "incident_id": "different-incident"}
    ) is False



def test_recovery_requires_confirmed_durable_deactivation_contract() -> None:
    from pathlib import Path

    source = Path("bot/runtime_drawdown_stop_provenance_v414_patch.py").read_text(
        encoding="utf-8"
    )
    assert "deactivated = ks.deactivate(" in source
    assert "if deactivated is not True or bool(ks.is_active()) or not durable_inactive:" in source
    assert "durable_deactivation_not_confirmed" in source
