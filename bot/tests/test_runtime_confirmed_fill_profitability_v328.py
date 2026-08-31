from __future__ import annotations

import math

import pytest

from bot import runtime_confirmed_fill_profitability_v328_patch as v328


def test_pending_ack_never_becomes_fill_even_with_price_like_fields():
    with pytest.raises(RuntimeError, match="ACK timeout pending reconciliation"):
        v328._normalize_dict_fill(
            {
                "status": "pending",
                "order_id": "ACK-1",
                "price": 100.0,
                "size_usd": 25.0,
            },
            symbol="BTC-USD",
            side="buy",
        )


def test_generic_price_and_requested_notional_are_not_fill_proof():
    with pytest.raises(RuntimeError, match="fill_specific_price_or_notional_missing"):
        v328._normalize_dict_fill(
            {
                "status": "filled",
                "order_id": "ACK-2",
                "price": 100.0,
                "notional_usd": 25.0,
                "size_usd": 25.0,
            },
            symbol="BTC-USD",
            side="buy",
        )


def test_confirmed_fill_specific_price_and_notional_pass():
    price, filled = v328._normalize_dict_fill(
        {
            "status": "filled",
            "order_id": "FILL-1",
            "average_filled_price": 101.25,
            "filled_size_usd": 25.0,
        },
        symbol="BTC-USD",
        side="buy",
    )
    assert price == 101.25
    assert filled == 25.0


def test_confirmed_fill_volume_can_build_notional():
    price, filled = v328._normalize_dict_fill(
        {
            "status": "closed",
            "order_id": "FILL-2",
            "filled_price": 50.0,
            "filled_volume": 0.4,
        },
        symbol="ETH-USD",
        side="sell",
    )
    assert price == 50.0
    assert filled == 20.0


def test_partial_fill_requires_reconciliation_not_success():
    with pytest.raises(RuntimeError, match="ACK timeout pending reconciliation"):
        v328._normalize_dict_fill(
            {
                "status": "partially_filled",
                "order_id": "PARTIAL-1",
                "filled_price": 100.0,
                "filled_volume": 0.1,
            },
            symbol="BTC-USD",
            side="buy",
        )


def test_missing_status_is_allowed_only_with_explicit_fill_fields():
    price, filled = v328._normalize_dict_fill(
        {
            "order_id": "FILL-3",
            "executed_price": 200.0,
            "executed_quantity": 0.1,
        },
        symbol="SOL-USD",
        side="buy",
    )
    assert price == 200.0
    assert filled == 20.0


def test_buy_and_sell_slippage_are_direction_aware():
    token = v328._MEASURED_SLIPPAGE_BPS.set(None)
    try:
        buy = v328._capture_slippage("buy", 101.0, 100.0)
        assert math.isclose(buy, 100.0, abs_tol=1e-12)
        sell = v328._capture_slippage("sell", 99.0, 100.0)
        assert math.isclose(sell, 100.0, abs_tol=1e-12)
        favorable_buy = v328._capture_slippage("buy", 99.0, 100.0)
        assert favorable_buy == 0.0
    finally:
        v328._MEASURED_SLIPPAGE_BPS.reset(token)


def test_reference_price_is_pretrade_input_not_fill_proof():
    meta = {"price_hint_usd": 123.45}
    assert v328._reference_price(meta) == 123.45
    assert v328._reference_price(meta, 120.0) == 120.0


def test_unknown_broker_slippage_is_not_recorded_as_perfect_zero():
    assert v328._patch_performance_scorer()
    from bot.broker_performance_scorer import BrokerPerformanceScorer

    scorer = BrokerPerformanceScorer(window=10, min_observations=1)
    token = v328._MEASURED_SLIPPAGE_BPS.set(None)
    try:
        scorer.record_order_result(
            broker="kraken",
            success=True,
            latency_ms=10.0,
            slippage_bps=0.0,
            error=None,
        )
    finally:
        v328._MEASURED_SLIPPAGE_BPS.reset(token)

    obs = list(scorer._states["kraken"]._observations)
    assert len(obs) == 1
    assert obs[0].slippage_bps == -1.0


def test_measured_exact_zero_slippage_remains_a_real_measurement():
    assert v328._patch_performance_scorer()
    from bot.broker_performance_scorer import BrokerPerformanceScorer

    scorer = BrokerPerformanceScorer(window=10, min_observations=1)
    token = v328._MEASURED_SLIPPAGE_BPS.set(0.0)
    try:
        scorer.record_order_result(
            broker="coinbase",
            success=True,
            latency_ms=10.0,
            slippage_bps=0.0,
            error=None,
        )
    finally:
        v328._MEASURED_SLIPPAGE_BPS.reset(token)

    obs = list(scorer._states["coinbase"]._observations)
    assert obs[0].slippage_bps == 0.0
