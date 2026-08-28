from __future__ import annotations

import sys
from types import ModuleType


def _fake_modules(monkeypatch):
    exchange = ModuleType("bot.exchange_kill_switch")

    class ExchangeKillSwitchProtector:
        def __init__(self):
            self.samples = []

        def record_order_result(self, order_id: str, accepted: bool):
            self.samples.append(bool(accepted))

    exchange.ExchangeKillSwitchProtector = ExchangeKillSwitchProtector
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", exchange)

    pipeline = ModuleType("bot.execution_pipeline")

    class ExecutionPipeline:
        def __init__(self, protector):
            self.protector = protector

        def _emit_execution_rejection_telemetry(self, *, symbol: str, side: str, reason: str):
            self.protector.record_order_result(
                order_id=f"exec-reject:pipeline:{symbol}:{side}",
                accepted=False,
            )

        def _on_order_rejected(self, request, error: str):
            self._emit_execution_rejection_telemetry(
                symbol=request.symbol,
                side=request.side,
                reason=error,
            )

    pipeline.ExecutionPipeline = ExecutionPipeline
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", pipeline)
    return exchange, pipeline


def test_v256_emitter_excludes_known_local_rejection(monkeypatch):
    from bot import exchange_reject_dispatch_provenance_v228_patch as patch

    exchange, pipeline = _fake_modules(monkeypatch)
    assert patch._patch_exchange_recorder() is True
    assert patch._patch_execution_pipeline() is True

    protector = exchange.ExchangeKillSwitchProtector()
    worker = pipeline.ExecutionPipeline(protector)
    request = type("Request", (), {"symbol": "BTC-USD", "side": "buy"})()

    worker._on_order_rejected(request, "dispatch_disabled: dispatch.enabled=false")

    assert protector.samples == []


def test_v256_recorder_fallback_excludes_known_local_rejection(monkeypatch):
    from bot import exchange_reject_dispatch_provenance_v228_patch as patch

    exchange, _pipeline = _fake_modules(monkeypatch)
    assert patch._patch_exchange_recorder() is True

    protector = exchange.ExchangeKillSwitchProtector()
    previous = patch._set_context(
        symbol="BTC-USD",
        side="buy",
        reason="dispatch_disabled: dispatch.enabled=false",
    )
    try:
        protector.record_order_result("exec-reject:pipeline:BTC-USD:buy", False)
    finally:
        patch._restore_context(previous)

    assert protector.samples == []
    provenance = list(protector._nija_order_result_provenance_v256)
    assert len(provenance) == 1
    assert provenance[0]["known_non_exchange"] is True
    assert "dispatch_disabled" in provenance[0]["reason"]


def test_v256_recorder_preserves_unclassified_exchange_rejection(monkeypatch):
    from bot import exchange_reject_dispatch_provenance_v228_patch as patch

    exchange, pipeline = _fake_modules(monkeypatch)
    assert patch._patch_exchange_recorder() is True
    assert patch._patch_execution_pipeline() is True

    protector = exchange.ExchangeKillSwitchProtector()
    worker = pipeline.ExecutionPipeline(protector)
    request = type("Request", (), {"symbol": "ETH-USD", "side": "buy"})()

    reason = "Kraken AddOrder rejected: EOrder:Insufficient funds"
    worker._on_order_rejected(request, reason)

    assert protector.samples == [False]
    provenance = list(protector._nija_order_result_provenance_v256)
    assert len(provenance) == 1
    assert provenance[0]["known_non_exchange"] is False
    assert provenance[0]["reason"] == reason


def test_v256_classifier_keeps_soft_ack_timeout_out_of_exchange_window():
    from bot import exchange_reject_dispatch_provenance_v228_patch as patch

    assert patch._is_non_exchange_rejection(
        "confirmed_order_rejected:ack_timeout_no_confirmed_fill"
    ) is True
    assert patch._is_non_exchange_rejection(
        "Kraken AddOrder rejected: EOrder:Insufficient funds"
    ) is False
