from __future__ import annotations

import logging
from types import SimpleNamespace

from bot import okx_patch_churn_guard_patch as patch


def _chain_with_marker(marker: str):
    def base(self, symbol, side, quantity):
        return symbol, side, quantity

    def own(self, symbol, side, quantity):
        return base(self, symbol, side, quantity)

    setattr(own, marker, True)
    own.__wrapped__ = base

    def foreign(self, symbol, side, quantity):
        return own(self, symbol, side, quantity)

    foreign.__wrapped__ = own
    return foreign


def test_marker_is_found_below_another_wrapper():
    marker = "_nija_test_marker"
    wrapped = _chain_with_marker(marker)
    assert patch._has_marker_chain(wrapped, marker) is True


def test_instid_patch_does_not_rewrap_when_marker_exists_in_chain():
    marker = "_nija_instid_marker"

    class OKXBroker:
        place_market_order = _chain_with_marker(marker)

    module = SimpleNamespace(
        __name__="bot.okx_order_instid_payload_repair_patch",
        _ORDER_WRAP_ATTR=marker,
        _MARKER="test",
        _normalize_inst_id=lambda value: str(value).replace("-USD", "-USDT"),
        logger=logging.getLogger("test.okx.instid"),
    )

    assert patch._guard_instid_module(module) is True
    before = OKXBroker.place_market_order
    assert module._wrap_order_class(OKXBroker, "bot.broker_manager") is False
    assert OKXBroker.place_market_order is before


def test_unmarked_method_is_wrapped_only_once():
    marker = "_nija_instid_once"

    class OKXBroker:
        def place_market_order(self, symbol, side, quantity):
            return symbol, side, quantity

    module = SimpleNamespace(
        __name__="bot.okx_order_instid_payload_repair_patch",
        _ORDER_WRAP_ATTR=marker,
        _MARKER="test",
        _normalize_inst_id=lambda value: str(value).replace("-USD", "-USDT"),
        logger=logging.getLogger("test.okx.once"),
    )

    patch._guard_instid_module(module)
    assert module._wrap_order_class(OKXBroker, "bot.broker_manager") is True
    first = OKXBroker.place_market_order
    assert module._wrap_order_class(OKXBroker, "bot.broker_manager") is False
    assert OKXBroker.place_market_order is first
    assert OKXBroker().place_market_order("APT-USD", "buy", 10) == ("APT-USDT", "buy", 10)


def test_generic_broker_module_names_no_longer_trigger_full_rescan():
    assert patch._narrow_interesting("bot.broker_manager") is True
    assert patch._narrow_interesting("bot.some_unrelated_broker_helper") is False
    assert patch._narrow_interesting("bot.okx_client") is True
