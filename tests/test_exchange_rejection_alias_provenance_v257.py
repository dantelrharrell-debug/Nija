from __future__ import annotations

import sys
from types import ModuleType


def _pipeline_module(name: str):
    module = ModuleType(name)

    class ExecutionPipeline:
        def __init__(self, protector):
            self.protector = protector

        def _emit_execution_rejection_telemetry(self, *, symbol: str, side: str, reason: str):
            self.protector.record_order_result(
                order_id=f"exec-reject:pipeline:{name}:{symbol}:{side}",
                accepted=False,
            )

        def _on_order_rejected(self, request, error: str):
            self._emit_execution_rejection_telemetry(
                symbol=request.symbol,
                side=request.side,
                reason=error,
            )

    module.ExecutionPipeline = ExecutionPipeline
    return module


def _exchange_module():
    module = ModuleType("bot.exchange_kill_switch")

    class ExchangeKillSwitchProtector:
        def __init__(self):
            self.samples = []

        def record_order_result(self, order_id: str, accepted: bool):
            self.samples.append(bool(accepted))

    module.ExchangeKillSwitchProtector = ExchangeKillSwitchProtector
    return module


def test_v257_patches_both_loaded_pipeline_identities(monkeypatch):
    from bot import exchange_reject_dispatch_provenance_v228_patch as patch

    exchange = _exchange_module()
    canonical = _pipeline_module("bot.execution_pipeline")
    legacy = _pipeline_module("execution_pipeline")
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", exchange)
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", canonical)
    monkeypatch.setitem(sys.modules, "execution_pipeline", legacy)

    assert patch._patch_exchange_recorder() is True
    assert patch._patch_execution_pipeline() is True

    request = type("Request", (), {"symbol": "BTC-USD", "side": "buy"})()
    protector = exchange.ExchangeKillSwitchProtector()
    canonical.ExecutionPipeline(protector)._on_order_rejected(
        request, "dispatch_disabled: dispatch.enabled=false"
    )
    legacy.ExecutionPipeline(protector)._on_order_rejected(
        request, "execution_authority_blocked:dispatch_scope_missing"
    )
    assert protector.samples == []


def test_v257_concrete_exchange_rejection_still_counts(monkeypatch):
    from bot import exchange_reject_dispatch_provenance_v228_patch as patch

    exchange = _exchange_module()
    canonical = _pipeline_module("bot.execution_pipeline")
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", exchange)
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", canonical)
    monkeypatch.delitem(sys.modules, "execution_pipeline", raising=False)

    assert patch._patch_exchange_recorder() is True
    assert patch._patch_execution_pipeline() is True

    request = type("Request", (), {"symbol": "ETH-USD", "side": "buy"})()
    protector = exchange.ExchangeKillSwitchProtector()
    canonical.ExecutionPipeline(protector)._on_order_rejected(
        request, "Kraken AddOrder rejected: EOrder:Insufficient funds"
    )
    assert protector.samples == [False]


def test_v257_direct_missing_context_rejection_remains_fail_closed(monkeypatch):
    from bot import exchange_reject_dispatch_provenance_v228_patch as patch

    exchange = _exchange_module()
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", exchange)
    assert patch._patch_exchange_recorder() is True

    protector = exchange.ExchangeKillSwitchProtector()
    protector.record_order_result(order_id="legacy-direct:1", accepted=False)

    assert protector.samples == [False]
    provenance = list(protector._nija_order_result_provenance_v256)
    assert provenance[-1]["source"] == "direct_or_legacy"
    assert provenance[-1]["reason"] == ""
