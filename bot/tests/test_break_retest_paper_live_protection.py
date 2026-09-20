from __future__ import annotations

import time

import pytest

import bot.safety_controller as safety_controller
from bot.execution_pipeline import ExecutionPipeline, PipelineRequest, PipelineResult


def _set_paper_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_STORE_MODE", "false")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "true")
    # Deliberately leave live authorization requested to prove PAPER_MODE wins
    # and cannot accidentally fall through to real-money dispatch.
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("HEARTBEAT_TRADE", "false")


def test_paper_mode_maps_to_simulated_trading(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    _set_paper_mode(monkeypatch)

    controller = safety_controller.SafetyController()

    assert controller.get_current_mode() is safety_controller.TradingMode.DRY_RUN
    allowed, reason = controller.is_trading_allowed()
    assert allowed is True
    assert "simulated" in reason.lower()
    assert controller.is_simulator_allowed() is True


def test_break_retest_paper_entry_simulates_before_any_router_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _set_paper_mode(monkeypatch)
    monkeypatch.setattr(safety_controller, "_safety_controller", None)

    pipeline = object.__new__(ExecutionPipeline)
    simulated = []

    def _simulate(request, t_start, mode_value, reason):
        simulated.append((request.strategy, mode_value, reason))
        return PipelineResult(
            success=True,
            symbol=request.symbol,
            side=request.side,
            size_usd=float(request.size_usd or 0.0),
            broker=f"{mode_value}_simulated",
        )

    pipeline._simulate_execution = _simulate

    request = PipelineRequest(
        strategy="BREAK_RETEST",
        symbol="BTC-USD",
        side="buy",
        size_usd=25.0,
        intent_type="entry",
        stop_loss_pct=0.01,
        take_profit_pct=0.02,
        price_hint_usd=100.0,
        preferred_broker="kraken",
    )

    result = pipeline._enforce_execution_gate(request, time.monotonic())

    assert result is not None
    assert result.success is True
    assert result.broker == "dry_run_simulated"
    assert simulated and simulated[0][0] == "BREAK_RETEST"
    assert simulated[0][1] == "dry_run"
