from bot import runtime_kraken_addorder_txid_capture_v369_patch as v369


def test_extract_txid_requires_successful_addorder_shape():
    assert v369._extract_txids({"error": [], "result": {"txid": ["OID-1"]}}) == ["OID-1"]
    assert v369._extract_txids({"error": ["EOrder:fail"], "result": {"txid": ["BAD"]}}) == []
    assert v369._extract_txids({"result": {}}) == []


def test_addorder_txid_is_recorded_but_never_promoted_to_fill(monkeypatch):
    recorded = []

    class FakeKraken:
        def _kraken_private_call(self, endpoint, params=None, *args, **kwargs):
            return {"error": [], "result": {"txid": ["OID-EXACT"], "descr": {"order": "buy"}}}

    monkeypatch.setattr(
        v369,
        "_record",
        lambda txid, params: recorded.append((txid, dict(params or {}))) or True,
    )

    assert v369._patch_class(FakeKraken) is True
    broker = FakeKraken()
    result = broker._kraken_private_call(
        "AddOrder", {"pair": "XETHZUSD", "type": "buy", "ordertype": "market"}
    )

    assert result["result"]["txid"] == ["OID-EXACT"]
    assert recorded == [
        ("OID-EXACT", {"pair": "XETHZUSD", "type": "buy", "ordertype": "market"})
    ]


def test_non_addorder_private_calls_are_not_recorded(monkeypatch):
    recorded = []

    class FakeKraken:
        def _kraken_private_call(self, endpoint, params=None, *args, **kwargs):
            return {"error": [], "result": {"txid": ["UNRELATED"]}}

    monkeypatch.setattr(v369, "_record", lambda *args, **kwargs: recorded.append(args) or True)
    assert v369._patch_class(FakeKraken) is True
    FakeKraken()._kraken_private_call("QueryOrders", {"txid": "OID"})
    assert recorded == []


def test_multiple_txids_are_kept_exact_and_distinct(monkeypatch):
    recorded = []

    class FakeKraken:
        def _kraken_private_call(self, endpoint, params=None, *args, **kwargs):
            return {"error": [], "result": {"txid": ["OID-A", "OID-B"]}}

    monkeypatch.setattr(
        v369, "_record", lambda txid, params: recorded.append(txid) or True
    )
    assert v369._patch_class(FakeKraken) is True
    FakeKraken()._kraken_private_call("AddOrder", {"pair": "XBTUSD", "type": "buy"})
    assert recorded == ["OID-A", "OID-B"]
