from __future__ import annotations

from types import ModuleType


def test_payload_style_okx_order_call_is_normalized_without_missing_args():
    import bot.okx_final_order_submission_bridge_patch as patch

    class OKXBroker:
        NAME = "okx"

        def place_order(self, payload):
            return {"status": "submitted", "payload": payload}

    module = ModuleType("fake_okx_payload_broker_module")
    module.OKXBroker = OKXBroker

    assert patch._patch_module(module)

    response = OKXBroker().place_order({"instId": "ARB-USD", "side": "buy", "sz": "12.50"})

    assert response["status"] == "submitted"
    assert response["payload"]["instId"] == "ARB-USDT"
    assert response["payload"]["side"] == "buy"
    assert float(response["payload"]["sz"]) == 12.5


def test_keyword_style_okx_order_call_reaches_positional_adapter():
    import bot.okx_final_order_submission_bridge_patch as patch

    class OKXBrokerAdapter:
        NAME = "okx"

        def place_market_order(self, symbol, side, quantity, **kwargs):
            return {
                "status": "submitted",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "size_type": kwargs.get("size_type"),
            }

    module = ModuleType("fake_okx_keyword_broker_module")
    module.OKXBrokerAdapter = OKXBrokerAdapter

    assert patch._patch_module(module)

    response = OKXBrokerAdapter().place_market_order(
        symbol="ARB-USD",
        side="buy",
        quantity=87.02,
        size_type="quote",
    )

    assert response["status"] == "submitted"
    assert response["symbol"] == "ARB-USDT"
    assert response["side"] == "buy"
    assert response["quantity"] == 87.02
    assert response["size_type"] == "quote"


def test_invalid_okx_order_shape_returns_clear_callshape_block():
    import bot.okx_final_order_submission_bridge_patch as patch

    class OKXBroker:
        NAME = "okx"

        def place_market_order(self, symbol, side, quantity, **kwargs):
            return {"status": "submitted"}

    module = ModuleType("fake_okx_bad_shape_broker_module")
    module.OKXBroker = OKXBroker

    assert patch._patch_module(module)

    response = OKXBroker().place_market_order({"instId": "ARB-USD", "side": "buy"})

    assert response["status"] == "error"
    assert response["error_code"] == "OKX_CALLSHAPE_BLOCK"
    assert "missing_or_invalid_order_fields" in response["error"]


def test_router_okx_direct_dispatch_logs_and_accepts_ack_with_price_hint():
    import bot.okx_final_order_submission_bridge_patch as patch
    import bot.multi_broker_execution_router as router_module

    patch._patch_module(router_module)

    class OKXBrokerAdapter:
        NAME = "okx"

        def place_market_order(self, symbol, side, quantity, **kwargs):
            return {
                "status": "submitted",
                "order_id": "okx-test-order-1",
                "symbol": symbol,
                "side": side,
                "filled_price": 1.25,
                "filled_size_usd": quantity,
            }

    fill_price, filled_usd = router_module.MultiBrokerExecutionRouter._dispatch_direct_broker_market_order(
        OKXBrokerAdapter(),
        symbol="ARB-USD",
        side="buy",
        size_usd=87.02,
        metadata={"price_hint_usd": 1.25, "min_notional_usd": 10.0},
    )

    assert fill_price == 1.25
    assert filled_usd == 87.02
