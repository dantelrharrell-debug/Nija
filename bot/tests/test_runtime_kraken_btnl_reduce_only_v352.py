from __future__ import annotations

import importlib


def _patch():
    return importlib.import_module("bot.runtime_kraken_btnl_reduce_only_v352_patch")


def test_btnl_pair_uses_existing_v261_legacy_mapping():
    p = _patch()
    assert p._btnl_pair("XETHZUSD") == "ETH/USD:BTNL"
    assert p._btnl_pair("XXBTZUSD") == "BTC/USD:BTNL"
    assert p._btnl_pair("ETH-USD") == "ETH/USD:BTNL"


def test_btnl_pair_never_guesses_unknown_compact_pair():
    p = _patch()
    assert p._btnl_pair("UNKNOWNUDS") == ""


def test_exact_non_ecp_error_detection():
    p = _patch()
    assert p._is_non_ecp_reduce_only({"error": ["EOrder:Reduce only:Non-ECP"]}) is True
    assert p._is_non_ecp_reduce_only(RuntimeError("EOrder:Reduce only:Non-ECP")) is True
    assert p._is_non_ecp_reduce_only({"error": ["EOrder:Insufficient funds"]}) is False


def test_retry_occurs_once_only_for_leveraged_reduce_only_non_ecp():
    p = _patch()
    v223 = importlib.import_module("bot.kraken_margin_auto_runtime_patch")

    class FakeKraken:
        account_identifier = "platform"

        def __init__(self):
            self.calls = []

        def _kraken_private_call(self, method, params=None, *args, **kwargs):
            payload = dict(params or {})
            self.calls.append((method, payload))
            if payload.get("pair") == "XETHZUSD":
                return {"error": ["EOrder:Reduce only:Non-ECP"]}
            return {"error": [], "result": {"txid": ["REAL-ORDER-ID"]}}

    assert p._patch_kraken_class(FakeKraken) is True
    broker = FakeKraken()
    with v223._margin_order_scope(2, True):
        result = broker._kraken_private_call(
            "AddOrder",
            {"pair": "XETHZUSD", "type": "sell", "ordertype": "market", "volume": "0.01"},
        )

    assert result["error"] == []
    assert len(broker.calls) == 2
    assert broker.calls[0][1]["pair"] == "XETHZUSD"
    assert broker.calls[1][1]["pair"] == "ETH/USD:BTNL"


def test_non_reduce_only_order_is_never_rerouted():
    p = _patch()
    v223 = importlib.import_module("bot.kraken_margin_auto_runtime_patch")

    class FakeKraken:
        def __init__(self):
            self.calls = []

        def _kraken_private_call(self, method, params=None, *args, **kwargs):
            payload = dict(params or {})
            self.calls.append((method, payload))
            return {"error": ["EOrder:Reduce only:Non-ECP"]}

    assert p._patch_kraken_class(FakeKraken) is True
    broker = FakeKraken()
    with v223._margin_order_scope(2, False):
        result = broker._kraken_private_call("AddOrder", {"pair": "XETHZUSD", "type": "sell"})

    assert p._is_non_ecp_reduce_only(result) is True
    assert len(broker.calls) == 1
