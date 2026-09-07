from bot import runtime_kraken_btnl_index_trigger_v396_patch as v396


def test_is_btnl():
    assert v396._is_btnl("ETHUSD:BTNL") is True
    assert v396._is_btnl("ETHUSD") is False


def test_patch_adds_index_only_to_btnl_conditional(monkeypatch):
    captured = []

    def original_call(broker, method, params, category_name):
        captured.append((method, dict(params), category_name))
        return {"error": [], "result": {"txid": ["OID"]}}

    class FakeV380:
        _call = staticmethod(original_call)

    real_import = v396.importlib.import_module
    monkeypatch.setattr(v396.importlib, "import_module", lambda name: FakeV380 if name.endswith("v380_patch") else real_import(name))

    assert v396._patch_v380_call() is True
    FakeV380._call(None, "AddOrder", {
        "pair": "ETHUSD:BTNL", "ordertype": "stop-loss", "reduce_only": True, "leverage": "2"
    }, "EXIT")
    assert captured[-1][1]["trigger"] == "index"

    FakeV380._call(None, "AddOrder", {
        "pair": "ETHUSD", "ordertype": "stop-loss", "reduce_only": True, "leverage": "2"
    }, "EXIT")
    assert "trigger" not in captured[-1][1]
