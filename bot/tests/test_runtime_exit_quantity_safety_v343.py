from __future__ import annotations

import pytest

from bot.runtime_exit_quantity_safety_v343_patch import (
    _invoke_submit_signature_safe,
    _safe_terminal_base_quantity,
)


def test_v343_clamps_prove_exit_to_verified_position_when_pipeline_notional_is_larger():
    metadata = {
        "verified_position_quantity": 11.71387,
        "price_hint_usd": 0.1731,
    }
    terminal, verified, price = _safe_terminal_base_quantity(5.193, metadata)
    assert verified == pytest.approx(11.71387)
    assert price == pytest.approx(0.1731)
    assert terminal == pytest.approx(11.71387)
    assert terminal <= verified


def test_v343_clamps_orca_exit_to_verified_position_when_pipeline_notional_is_larger():
    metadata = {
        "verified_position_quantity": 3.00125809,
        "price_hint_usd": 1.202,
    }
    terminal, verified, price = _safe_terminal_base_quantity(6.01, metadata)
    assert verified == pytest.approx(3.00125809)
    assert price == pytest.approx(1.202)
    assert terminal == pytest.approx(3.00125809)
    assert terminal <= verified


def test_v343_uses_smaller_compiled_quantity_for_partial_close():
    metadata = {
        "verified_position_quantity": 10.0,
        "price_hint_usd": 2.0,
    }
    terminal, verified, _ = _safe_terminal_base_quantity(8.0, metadata)
    assert terminal == pytest.approx(4.0)
    assert terminal < verified


def test_v343_fails_closed_when_verified_position_is_missing():
    with pytest.raises(RuntimeError, match="verified_position_quantity_missing"):
        _safe_terminal_base_quantity(5.0, {"price_hint_usd": 1.0})


def test_v343_fails_closed_when_price_is_missing():
    with pytest.raises(RuntimeError, match="protective_exit_price_missing"):
        _safe_terminal_base_quantity(5.0, {"verified_position_quantity": 2.0})


def test_v343_signature_safe_submit_does_not_retry_internal_typeerror():
    calls = []

    def submit(symbol: str, side: str, size: float, size_type: str = "base"):
        calls.append((symbol, side, size, size_type))
        raise TypeError("'<=' not supported between instances of 'NoneType' and 'int'")

    with pytest.raises(TypeError, match="NoneType"):
        _invoke_submit_signature_safe(
            submit,
            "BTC-USD",
            "sell",
            0.001,
            {"size_type": "base"},
        )

    assert calls == [("BTC-USD", "sell", pytest.approx(0.001), "base")]


def test_v343_signature_safe_submit_supports_quantity_keyword_contract():
    observed = {}

    def submit(*, symbol: str, side: str, quantity: float, size_type: str = "base"):
        observed.update(symbol=symbol, side=side, quantity=quantity, size_type=size_type)
        return {"status": "filled", "order_id": "abc"}

    result = _invoke_submit_signature_safe(
        submit,
        "ETH-USD",
        "sell",
        0.25,
        {"size_type": "base"},
    )
    assert result["order_id"] == "abc"
    assert observed == {
        "symbol": "ETH-USD",
        "side": "sell",
        "quantity": pytest.approx(0.25),
        "size_type": "base",
    }
