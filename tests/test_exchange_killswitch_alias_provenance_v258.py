from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import bot.exchange_kill_switch_alias_provenance_v258_patch as v258


def _kill_module(name: str) -> ModuleType:
    module = ModuleType(name)

    class Protector:
        def __init__(self) -> None:
            self._cfg = SimpleNamespace(order_window_size=20)
            self._order_results: list[bool] = []

        def record_order_result(self, order_id: str, accepted: bool):
            self._order_results.append(bool(accepted))
            return "recorded"

    module.ExchangeKillSwitchProtector = Protector
    module._protector = Protector()
    return module


def _pipeline_module(name: str, recorder):
    module = ModuleType(name)

    class ExecutionPipeline:
        def _emit_execution_rejection_telemetry(self, *, symbol: str, side: str, reason: str):
            return recorder(f"exec-reject:{symbol}:{side}", False)

        def _on_order_rejected(self, request, error: str):
            return self._emit_execution_rejection_telemetry(
                symbol=request.symbol,
                side=request.side,
                reason=error,
            )

    module.ExecutionPipeline = ExecutionPipeline
    return module


def test_v258_patches_both_kill_switch_identities(monkeypatch):
    canonical = _kill_module("bot.exchange_kill_switch")
    legacy = _kill_module("exchange_kill_switch")
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", canonical)
    monkeypatch.setitem(sys.modules, "exchange_kill_switch", legacy)

    assert v258._patch_kill_switch_module(canonical) is True
    assert v258._patch_kill_switch_module(legacy) is True

    canonical._protector.record_order_result("canonical-reject", False)
    legacy._protector.record_order_result("legacy-reject", False)

    assert canonical._protector._order_results == [False]
    assert legacy._protector._order_results == [False]
    assert canonical._protector._nija_order_result_provenance_v258[-1]["kill_switch_module"] == "bot.exchange_kill_switch"
    assert legacy._protector._nija_order_result_provenance_v258[-1]["kill_switch_module"] == "exchange_kill_switch"


def test_v258_local_predispatch_reason_is_not_counted(monkeypatch):
    legacy = _kill_module("exchange_kill_switch")
    monkeypatch.setitem(sys.modules, "exchange_kill_switch", legacy)
    assert v258._patch_kill_switch_module(legacy) is True

    pipeline_module = _pipeline_module(
        "execution_pipeline",
        legacy._protector.record_order_result,
    )
    monkeypatch.setitem(sys.modules, "execution_pipeline", pipeline_module)
    assert v258._patch_pipeline_module(pipeline_module) is True

    request = SimpleNamespace(symbol="BTC-USD", side="buy")
    result = pipeline_module.ExecutionPipeline()._on_order_rejected(
        request,
        "dispatch_disabled: dispatch.enabled=false",
    )

    assert result is None
    assert legacy._protector._order_results == []
    history = list(legacy._protector._nija_order_result_provenance_v258)
    assert history[-1]["known_non_exchange"] is True
    assert history[-1]["reason"] == "dispatch_disabled: dispatch.enabled=false"


def test_v269_exact_hardening_enforcement_is_local_predispatch(monkeypatch):
    canonical = _kill_module("bot.exchange_kill_switch")
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", canonical)
    assert v258._patch_kill_switch_module(canonical) is True

    pipeline_module = _pipeline_module(
        "bot.execution_pipeline",
        canonical._protector.record_order_result,
    )
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", pipeline_module)
    assert v258._patch_pipeline_module(pipeline_module) is True

    request = SimpleNamespace(symbol="BTC-USD", side="buy")
    result = pipeline_module.ExecutionPipeline()._on_order_rejected(
        request,
        "HARDENING_ENFORCEMENT",
    )

    assert result is None
    assert canonical._protector._order_results == []
    history = list(canonical._protector._nija_order_result_provenance_v258)
    assert history[-1]["known_non_exchange"] is True
    assert history[-1]["source"] == "execution_pipeline"
    assert history[-1]["reason"] == "HARDENING_ENFORCEMENT"


def test_v269_hardening_token_inside_exchange_message_still_counts(monkeypatch):
    canonical = _kill_module("bot.exchange_kill_switch")
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", canonical)
    assert v258._patch_kill_switch_module(canonical) is True

    pipeline_module = _pipeline_module(
        "bot.execution_pipeline",
        canonical._protector.record_order_result,
    )
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", pipeline_module)
    assert v258._patch_pipeline_module(pipeline_module) is True

    request = SimpleNamespace(symbol="BTC-USD", side="buy")
    reason = "Coinbase rejected order: HARDENING_ENFORCEMENT upstream policy"
    result = pipeline_module.ExecutionPipeline()._on_order_rejected(request, reason)

    assert result == "recorded"
    assert canonical._protector._order_results == [False]
    history = list(canonical._protector._nija_order_result_provenance_v258)
    assert history[-1]["known_non_exchange"] is False
    assert history[-1]["reason"] == reason


def test_v258_genuine_exchange_reject_still_counts(monkeypatch):
    canonical = _kill_module("bot.exchange_kill_switch")
    monkeypatch.setitem(sys.modules, "bot.exchange_kill_switch", canonical)
    assert v258._patch_kill_switch_module(canonical) is True

    pipeline_module = _pipeline_module(
        "bot.execution_pipeline",
        canonical._protector.record_order_result,
    )
    monkeypatch.setitem(sys.modules, "bot.execution_pipeline", pipeline_module)
    assert v258._patch_pipeline_module(pipeline_module) is True

    request = SimpleNamespace(symbol="BTC-USD", side="buy")
    result = pipeline_module.ExecutionPipeline()._on_order_rejected(
        request,
        "Coinbase order rejected: insufficient liquidity",
    )

    assert result == "recorded"
    assert canonical._protector._order_results == [False]
    history = list(canonical._protector._nija_order_result_provenance_v258)
    assert history[-1]["known_non_exchange"] is False
    assert history[-1]["source"] == "execution_pipeline"
    assert "Coinbase order rejected" in history[-1]["reason"]
