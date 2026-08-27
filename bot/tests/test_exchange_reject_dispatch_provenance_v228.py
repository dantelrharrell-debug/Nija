from __future__ import annotations

from bot.exchange_kill_switch import ExchangeKillSwitchConfig, ExchangeKillSwitchProtector
from bot import exchange_reject_dispatch_provenance_v228_patch as v228
import bot.execution_pipeline as execution_pipeline


def _protector(tmp_path):
    cfg = ExchangeKillSwitchConfig(auto_trigger_enabled=False)
    protector = ExchangeKillSwitchProtector(cfg)
    protector.STATE_FILE = tmp_path / "exchange_kill_switch_state.json"
    protector.reset("v228 test isolation")
    return protector


def _pipeline_stub():
    return execution_pipeline.ExecutionPipeline.__new__(execution_pipeline.ExecutionPipeline)


def test_non_exchange_classifier_covers_predispatch_failures():
    reasons = (
        "dispatch_disabled: dispatch.enabled=false",
        "ExecutionAuthority reject: SEAK halted (emergency stop)",
        "Execution gate pending (state_machine=EMERGENCY_STOP)",
        "Runtime authority convergence lost",
        "ExchangeKillSwitch: exchange health RED — trade blocked",
        "LiquidityIntelligenceEngine: liquidity grade below FAIR",
        "No available venue found for order routing",
        "BROKER_ADAPTER_NOT_CONNECTED",
        "RiskGovernor blocked: risk budget exhausted",
        "ECEL reject: local contract unavailable",
    )
    for reason in reasons:
        assert v228._is_non_exchange_rejection(reason) is True


def test_v247_classifier_covers_startup_lifecycle_denials_without_exchange_proof():
    reasons = (
        "lifecycle_phase:BOOT",
        "Execution blocked: lifecycle_phase:BOOT",
        "lifecycle_phase_not_live",
        "ExecutionAuthority reject: lifecycle_phase_not_live",
    )
    for reason in reasons:
        assert v228._is_non_exchange_rejection(reason) is True


def test_v232_classifier_covers_route_guard_soft_failures_without_exchange_proof():
    reasons = (
        "broker_dispatch_failed:kraken:none_result",
        "broker_dispatch_failed:coinbase:empty_order_result",
        "empty order result from adapter",
        "execution_route_mismatch:selected=kraken:actual=coinbase:symbol=BTC-USD",
        "BrokerRouteGuard deny: broker disabled for live execution selected=okx",
        "adapter_exception: TimeoutError",
        "broker_dispatch_exception: RuntimeError",
        "OKX order failed",
        "all operations failed",
    )
    for reason in reasons:
        assert v228._is_non_exchange_rejection(reason) is True


def test_classifier_does_not_swallow_unclassified_exchange_rejects():
    assert v228._is_non_exchange_rejection("Kraken AddOrder rejected: EOrder:Insufficient margin") is False
    assert v228._is_non_exchange_rejection("Coinbase order rejected: UNKNOWN_EXCHANGE_FAILURE") is False


def test_dispatch_disabled_does_not_mutate_exchange_rejection_window(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(execution_pipeline, "get_exchange_kill_switch_protector", lambda: protector)
    assert v228._patch_execution_pipeline()

    execution_pipeline.ExecutionPipeline._emit_execution_rejection_telemetry(
        _pipeline_stub(),
        symbol="BTC-USD",
        side="buy",
        reason="dispatch_disabled: dispatch.enabled=false",
    )

    assert list(protector._order_results) == []


def test_v247_boot_lifecycle_denial_does_not_mutate_exchange_rejection_window(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(execution_pipeline, "get_exchange_kill_switch_protector", lambda: protector)
    assert v228._patch_execution_pipeline()

    execution_pipeline.ExecutionPipeline._emit_execution_rejection_telemetry(
        _pipeline_stub(),
        symbol="BTC-USD",
        side="buy",
        reason="Execution blocked: lifecycle_phase:BOOT",
    )

    assert list(protector._order_results) == []


def test_v232_route_soft_failure_does_not_mutate_exchange_rejection_window(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(execution_pipeline, "get_exchange_kill_switch_protector", lambda: protector)
    assert v228._patch_execution_pipeline()

    execution_pipeline.ExecutionPipeline._emit_execution_rejection_telemetry(
        _pipeline_stub(),
        symbol="BTC-USD",
        side="buy",
        reason="broker_dispatch_failed:kraken:empty_order_result",
    )

    assert list(protector._order_results) == []


def test_unknown_exchange_reject_still_reaches_exchange_monitor(tmp_path, monkeypatch):
    protector = _protector(tmp_path)
    monkeypatch.setattr(execution_pipeline, "get_exchange_kill_switch_protector", lambda: protector)
    assert v228._patch_execution_pipeline()

    execution_pipeline.ExecutionPipeline._emit_execution_rejection_telemetry(
        _pipeline_stub(),
        symbol="BTC-USD",
        side="buy",
        reason="Kraken AddOrder rejected: EOrder:Insufficient margin",
    )

    assert list(protector._order_results) == [False]
