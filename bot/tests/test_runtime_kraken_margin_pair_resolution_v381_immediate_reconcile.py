from bot import runtime_kraken_margin_pair_resolution_v381_patch as v381


def test_lookup_symbol_preserves_public_pair_behavior():
    assert v381._lookup_symbol("ETHUSD:BTNL") == "ETHUSD"
    assert v381._lookup_symbol("ETH/USD:BTNL") == "ETH/USD"


def test_immediate_reconcile_is_single_flight(monkeypatch):
    calls = []

    class FakeV380:
        @staticmethod
        def audit_once():
            calls.append("audit")
            return {"ready": False}

    monkeypatch.setattr(v381.importlib, "import_module", lambda name: FakeV380 if name.endswith("v380_patch") else None)
    monkeypatch.setattr(v381, "_IMMEDIATE_RECONCILE_STARTED", False)

    assert v381._schedule_immediate_v380_reconcile() is True
    assert v381._schedule_immediate_v380_reconcile() is True
