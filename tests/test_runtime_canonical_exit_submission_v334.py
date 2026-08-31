from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


def _universal():
    return SimpleNamespace(
        _account_label=lambda broker: "platform",
        auto_exit=SimpleNamespace(
            _sym=lambda value: str(value),
            _quantity=lambda pos: float(pos["quantity"]),
            _side=lambda side, pos: str(side or pos.get("side") or "long"),
            _broker_label=lambda broker: "kraken",
        ),
    )


def test_canonical_submit_marks_base_quantity_as_explicit_exit(monkeypatch):
    from bot import runtime_canonical_exit_submission_v334_patch as v334

    captured = {}
    submitter = ModuleType("bot.pipeline_order_submitter")

    def submit_market_order_via_pipeline(**kwargs):
        captured.update(kwargs)
        return {"status": "filled", "order_id": "OID-1", "filled_price": 2467.0}

    submitter.submit_market_order_via_pipeline = submit_market_order_via_pipeline
    monkeypatch.setitem(sys.modules, "bot.pipeline_order_submitter", submitter)

    result = v334._canonical_submit(
        _universal(),
        SimpleNamespace(),
        {"symbol": "ETH-USD", "quantity": 0.09565438, "side": "long"},
        strategy_prefix="UniversalProtectiveExit",
    )

    assert result["status"] == "filled"
    assert captured["size_type"] == "base"
    assert captured["quantity"] == 0.09565438
    assert captured["side"] == "sell"
    assert captured["intent_type"] == "exit"
    assert captured["position_effect"] == "close"
    assert captured["metadata_override"]["closing_position"] is True


def test_unacknowledged_skipped_result_never_becomes_pending(monkeypatch):
    from bot import runtime_canonical_exit_submission_v334_patch as v334

    submitter = ModuleType("bot.pipeline_order_submitter")
    submitter.submit_market_order_via_pipeline = lambda **kwargs: {
        "status": "skipped",
        "success": True,
    }
    monkeypatch.setitem(sys.modules, "bot.pipeline_order_submitter", submitter)

    result = v334._canonical_submit(
        _universal(),
        SimpleNamespace(),
        {"symbol": "ETH-USD", "quantity": 1.0, "side": "long"},
        strategy_prefix="UniversalProtectiveExit",
    )

    assert result["status"] == "error"
    assert result["canonical_exit_unacknowledged"] is True
    assert v334._order_id(result) == ""


def test_real_pending_order_requires_order_id(monkeypatch):
    from bot import runtime_canonical_exit_submission_v334_patch as v334

    submitter = ModuleType("bot.pipeline_order_submitter")
    submitter.submit_market_order_via_pipeline = lambda **kwargs: {
        "status": "accepted",
        "order_id": "OID-2",
    }
    monkeypatch.setitem(sys.modules, "bot.pipeline_order_submitter", submitter)

    result = v334._canonical_submit(
        _universal(),
        SimpleNamespace(),
        {"symbol": "ETH-USD", "quantity": 1.0, "side": "long"},
        strategy_prefix="UniversalProtectiveExit",
    )

    assert result["status"] == "accepted"
    assert v334._order_id(result) == "OID-2"
