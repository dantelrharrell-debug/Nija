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
