from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from bot import runtime_kraken_short_terminal_integrity_v326_patch as v326


def test_confirmed_fill_requires_real_fill_evidence():
    price, filled_usd = v326._normalize_confirmed_fill(
        {
            "status": "filled",
            "order_id": "O-1",
            "filled_price": 100.0,
            "filled_volume": 0.25,
        },
        symbol="BTC-USD",
        side="sell",
        size_usd=25.0,
    )
    assert price == 100.0
    assert filled_usd == 25.0


def test_pending_ack_is_not_promoted_to_fill():
    with pytest.raises(RuntimeError, match="ACK timeout pending reconciliation"):
        v326._normalize_confirmed_fill(
            {
                "status": "pending",
                "order_id": "O-2",
                "filled_price": 0.0,
                "filled_volume": 0.0,
            },
            symbol="BTC-USD",
            side="sell",
            size_usd=25.0,
        )


def test_rejected_order_is_not_promoted_to_fill():
    with pytest.raises(RuntimeError, match="insufficient margin"):
        v326._normalize_confirmed_fill(
            {
                "status": "error",
                "error": "insufficient margin",
            },
            symbol="BTC-USD",
            side="sell",
            size_usd=25.0,
        )


def test_addorder_terminal_assertion_blocks_spot_fallback(monkeypatch):
    calls = []

    class _FakeKraken:
        def _kraken_api_call(self, method, params=None, *args, **kwargs):
            calls.append((method, dict(params or {})))
            return {"result": {}}

    fake_module = SimpleNamespace(KrakenBrokerAdapter=_FakeKraken)
    real_import = v326.importlib.import_module

    def import_module(name):
        if name == "bot.broker_integration":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(v326.importlib, "import_module", import_module)
    assert v326._patch_kraken_addorder_terminal_assertion()
    broker = _FakeKraken()

    token = v326._TERMINAL_SHORT_REQUIRED.set(True)
    try:
        with pytest.raises(RuntimeError, match="fail-closed"):
            broker._kraken_api_call(
                "AddOrder",
                {"type": "sell", "ordertype": "market", "volume": "0.1"},
            )
        assert calls == []

        response = broker._kraken_api_call(
            "AddOrder",
            {
                "type": "sell",
                "ordertype": "market",
                "volume": "0.1",
                "leverage": "2",
            },
        )
        assert response == {"result": {}}
        assert calls == [
            (
                "AddOrder",
                {
                    "type": "sell",
                    "ordertype": "market",
                    "volume": "0.1",
                    "leverage": "2",
                },
            )
        ]
    finally:
        v326._TERMINAL_SHORT_REQUIRED.reset(token)


def test_direct_router_propagates_margin_and_account_scope(monkeypatch):
    captured = {}
    scoped_accounts = []

    class _FakeRouter:
        @staticmethod
        def _dispatch_direct_broker_market_order(
            broker, *, symbol, side, size_usd, metadata
        ):
            raise AssertionError("legacy spot dispatcher must not handle v325 short")

    @contextmanager
    def margin_account_scope(account_id, adapter=None):
        scoped_accounts.append((account_id, adapter))
        yield object()

    fake_margin_module = SimpleNamespace(margin_account_scope=margin_account_scope)
    fake_router_module = SimpleNamespace(MultiBrokerExecutionRouter=_FakeRouter)
    real_import = v326.importlib.import_module

    def import_module(name):
        if name == "bot.multi_broker_execution_router":
            return fake_router_module
        if name == "bot.kraken_margin_engine":
            return fake_margin_module
        return real_import(name)

    monkeypatch.setattr(v326.importlib, "import_module", import_module)
    assert v326._patch_multi_broker_terminal_dispatch()

    class _Broker:
        broker_type = SimpleNamespace(value="kraken")

        def place_market_order(
            self,
            symbol,
            side,
            size,
            size_type="quote",
            leverage=1,
            reduce_only=None,
            margin_mode=None,
        ):
            captured.update(
                symbol=symbol,
                side=side,
                size=size,
                size_type=size_type,
                leverage=leverage,
                reduce_only=reduce_only,
                margin_mode=margin_mode,
                terminal_required=v326._TERMINAL_SHORT_REQUIRED.get(),
            )
            return {
                "status": "filled",
                "order_id": "SHORT-1",
                "filled_price": 50.0,
                "filled_volume": 0.5,
            }

    broker = _Broker()
    fill_price, filled_usd = _FakeRouter._dispatch_direct_broker_market_order(
        broker,
        symbol="ETH-USD",
        side="sell",
        size_usd=25.0,
        metadata={
            "kraken_margin_short_v325": True,
            "kraken_margin_account_id": "user-7",
            "leverage": 2,
            "reduce_only": False,
            "margin_mode": "cross",
        },
    )
    assert fill_price == 50.0
    assert filled_usd == 25.0
    assert captured == {
        "symbol": "ETH-USD",
        "side": "sell",
        "size": 25.0,
        "size_type": "quote",
        "leverage": 2,
        "reduce_only": False,
        "margin_mode": "cross",
        "terminal_required": True,
    }
    assert scoped_accounts == [("user-7", broker)]
