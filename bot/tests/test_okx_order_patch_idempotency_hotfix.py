from __future__ import annotations

import importlib
import logging
from types import ModuleType


def test_instid_patch_repeated_calls_wrap_once_and_keep_methods_functional(caplog):
    patch = importlib.import_module("bot.okx_order_instid_payload_repair_patch")
    patch = importlib.reload(patch)

    class OKXBroker:
        NAME = "okx"

        def place_market_order(self, symbol, side, quantity):
            return symbol, side, quantity

        def execute_order(self, symbol, side, quantity):
            return symbol, side, quantity

    module = ModuleType("fake_okx_instid_patch_module")
    module.OKXBroker = OKXBroker

    with caplog.at_level(logging.WARNING, logger="nija.okx_order_instid_payload_repair"):
        assert patch._patch_module(module) is True
        first_place = OKXBroker.place_market_order
        first_execute = OKXBroker.execute_order
        assert patch._patch_module(module) is False

    assert OKXBroker.place_market_order is first_place
    assert OKXBroker.execute_order is first_execute
    assert OKXBroker().place_market_order("ARB-USD", "buy", 5.0) == ("ARB-USDT", "buy", 5.0)
    assert OKXBroker().execute_order("ARB-USD", "sell", 3.0) == ("ARB-USDT", "sell", 3.0)
    assert sum("OKX_ORDER_SYMBOL_METHOD_PATCHED" in rec.getMessage() for rec in caplog.records) == 2


def test_final_patch_repeated_calls_wrap_once_and_keep_methods_functional(caplog):
    patch = importlib.import_module("bot.okx_final_order_submission_bridge_patch")
    patch = importlib.reload(patch)

    class OKXBroker:
        NAME = "okx"

        def place_market_order(self, symbol, side, quantity, **kwargs):
            return {"status": "submitted", "symbol": symbol, "side": side, "quantity": quantity, "kwargs": kwargs}

        def execute_order(self, symbol, side, quantity, **kwargs):
            return {"status": "submitted", "symbol": symbol, "side": side, "quantity": quantity, "kwargs": kwargs}

    module = ModuleType("fake_okx_final_patch_module")
    module.OKXBroker = OKXBroker

    with caplog.at_level(logging.WARNING, logger="nija.okx_final_order_submission_bridge"):
        assert patch._patch_module(module) is True
        first_place = OKXBroker.place_market_order
        first_execute = OKXBroker.execute_order
        assert patch._patch_module(module) is False

    assert OKXBroker.place_market_order is first_place
    assert OKXBroker.execute_order is first_execute

    place_resp = OKXBroker().place_market_order("ARB-USD", "buy", 25.0, size_type="quote")
    execute_resp = OKXBroker().execute_order("ARB-USD", "sell", 25.0, size_type="quote")
    assert place_resp["symbol"] == "ARB-USDT"
    assert execute_resp["symbol"] == "ARB-USDT"
    assert place_resp["status"] == "submitted"
    assert execute_resp["status"] == "submitted"
    assert sum("OKX_FINAL_ORDER_METHOD_PATCHED" in rec.getMessage() for rec in caplog.records) == 2
