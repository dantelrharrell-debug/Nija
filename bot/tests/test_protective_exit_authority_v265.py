from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from bot.pipeline_request_contract import PipelineRequest, validate_pipeline_request
from bot import runtime_protective_exit_authority_v265_patch as v265
from bot import kraken_all_account_exit_runtime_patch as kraken_exit


def test_pipeline_request_accepts_explicit_close_effect():
    request = PipelineRequest(
        strategy="protective-exit-test",
        symbol="ETH-USD",
        side="sell",
        size_usd=25.0,
        intent_type="exit",
        position_effect="close",
    )
    assert request.position_effect == "close"
    assert validate_pipeline_request(request) == (True, "ok")


def test_pipeline_request_rejects_entry_close_contradiction():
    request = PipelineRequest(
        strategy="entry-test",
        symbol="ETH-USD",
        side="buy",
        size_usd=25.0,
        intent_type="entry",
        position_effect="close",
    )
    assert validate_pipeline_request(request) == (False, "entry_intent_cannot_close_or_reduce")


def _fake_kraken_module() -> ModuleType:
    module = ModuleType("bot.kraken_all_account_exit_runtime_patch_test")

    def legacy_submit(broker, account, pair, quantity, reason):
        return {"status": "error", "error": "legacy path should be replaced"}

    module._submit_exit = legacy_submit
    return module


def test_kraken_protective_exit_is_explicit_close_and_preserves_account():
    captured = {}
    submitter = ModuleType("bot.pipeline_order_submitter")

    def submit_market_order_via_pipeline(**kwargs):
        captured.update(kwargs)
        return {
            "status": "filled",
            "order_id": "exit-1",
            "filled_price": 2500.0,
            "filled_size_usd": 25.0,
        }

    submitter.submit_market_order_via_pipeline = submit_market_order_via_pipeline
    fake_bot = sys.modules.get("bot")
    assert fake_bot is not None

    module = _fake_kraken_module()
    with patch.dict(sys.modules, {"bot.pipeline_order_submitter": submitter}, clear=False):
        assert v265._patch_kraken_exit_submit(module) is True
        result = module._submit_exit(
            SimpleNamespace(),
            "user:tania_gilbert:kraken",
            "ETHUSD",
            0.01,
            "emergency_stop_loss",
        )

    assert result["status"] == "filled"
    assert captured["side"] == "sell"
    assert captured["intent_type"] == "exit"
    assert captured["position_effect"] == "close"
    assert captured["account_id_override"] == "user:tania_gilbert:kraken"
    assert captured["metadata_override"]["closing_position"] is True
    assert captured["metadata_override"]["protective_exit"] is True


def test_kraken_ack_without_fill_remains_open():
    submitter = ModuleType("bot.pipeline_order_submitter")
    submitter.submit_market_order_via_pipeline = lambda **kwargs: {
        "status": "accepted",
        "order_id": "pending-123",
    }
    module = _fake_kraken_module()

    with patch.dict(sys.modules, {"bot.pipeline_order_submitter": submitter}, clear=False):
        assert v265._patch_kraken_exit_submit(module) is True
        result = module._submit_exit(
            SimpleNamespace(),
            "platform:kraken",
            "ETHUSD",
            0.01,
            "take_profit_1",
        )

    assert result["status"] == "error"
    assert result["error"] == "protective_exit_not_fill_confirmed"
    assert result["pending_order_id"] == "pending-123"
    assert v265._filled_result({"status": "accepted", "order_id": "pending-123"}) is False
    assert v265._filled_result({"status": "filled", "order_id": "filled-123"}) is True


def test_kraken_auto_exit_patch_preserves_optional_noarg_monitor_interface():
    module = ModuleType("bot.auto_exit_sl_tp_runtime_patch_test")
    calls = []

    def original_start_monitor(engine=None):
        calls.append(engine)
        return None

    module._start_monitor = original_start_monitor

    assert kraken_exit._patch_auto_exit_module(module) is True
    assert module._start_monitor() is None
    assert module._start_monitor(SimpleNamespace()) is None
    assert getattr(module._start_monitor, "_nija_account_local_disabled_v1", False) is True
    assert calls == []
