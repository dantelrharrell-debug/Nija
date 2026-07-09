from __future__ import annotations

from types import SimpleNamespace

from bot import direct_broker_venue_cash_hard_gate_patch as patch


class FakeOkxBroker:
    broker_type = "okx"
    NAME = "OKX"

    def __init__(self, payload):
        self._balance_cache = payload
        self.submitted = False

    def get_account_balance(self):
        # This is intentionally high to prove scalar OKX equity must not be
        # treated as spendable USDT/USDC quote cash.
        return {"available_balance": 146.26}

    def place_market_order(self, symbol, side, size_usd, size_type="quote"):
        self.submitted = True
        return {"status": "filled", "order_id": "real-okx-id", "filled_price": 1.0, "filled_size_usd": size_usd}


def test_okx_usdt_buy_blocks_when_only_scalar_equity_exists():
    broker = FakeOkxBroker({"data": [{"details": [{"ccy": "USD", "availBal": "146.26"}]}]})

    ok, available, required, label = patch._venue_cash_ok(
        broker,
        "okx",
        10.0,
        "buy",
        "direct_dispatch",
        "ADA-USDT",
    )

    assert ok is False
    assert available == 0.0
    assert required > 10.0
    assert label == "okx"
    assert broker.submitted is False


def test_okx_usdt_buy_allows_when_spendable_usdt_exists():
    broker = FakeOkxBroker({"data": [{"details": [{"ccy": "USDT", "availBal": "25.00"}]}]})

    ok, available, required, label = patch._venue_cash_ok(
        broker,
        "okx",
        10.0,
        "buy",
        "direct_dispatch",
        "ADA-USDT",
    )

    assert ok is True
    assert available == 25.0
    assert required > 10.0
    assert label == "okx"


def test_profile_rejects_okx_usdt_when_spendable_quote_missing():
    class FakeRouter:
        def _profile_for_direct_broker(self, asset_class, request):
            return SimpleNamespace(name="okx")

        def _dispatch_direct_broker_market_order(self, *args, **kwargs):
            return 1.0, 10.0

    module = SimpleNamespace(MultiBrokerExecutionRouter=FakeRouter, __name__="bot.multi_broker_execution_router")
    assert patch._patch_module(module) is True
    router = module.MultiBrokerExecutionRouter()
    broker = FakeOkxBroker({"data": [{"details": [{"ccy": "USD", "availBal": "146.26"}]}]})
    request = SimpleNamespace(symbol="ADA-USDT", side="buy", size_usd=10.0, metadata={"broker_client": broker})

    assert router._profile_for_direct_broker("spot", request) is None
    assert broker.submitted is False
