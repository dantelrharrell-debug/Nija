from types import SimpleNamespace

from bot import runtime_kraken_margin_pair_resolution_v381_patch as v381


def test_lookup_symbol_strips_only_synthetic_margin_suffix():
    assert v381._lookup_symbol("ETHUSD:BTNL") == "ETHUSD"
    assert v381._lookup_symbol("ETH-USD:BTNL") == "ETH-USD"
    assert v381._lookup_symbol("BTCUSDT:SHORT") == "BTCUSDT"
    assert v381._lookup_symbol("ETH-USD") == "ETH-USD"
    assert v381._lookup_symbol("CUSTOM:VALUE") == "CUSTOM:VALUE"


def test_pair_resolver_uses_exchange_pair_but_preserves_position_identity(monkeypatch):
    calls = []

    def current(broker, symbol):
        calls.append(symbol)
        return "ETHUSD" if symbol == "ETHUSD" else None

    module = SimpleNamespace(_resolve_pair=current)

    real_import = v381.importlib.import_module

    def fake_import(name):
        if name == "bot.kraken_all_account_exit_runtime_patch":
            return module
        return real_import(name)

    monkeypatch.setattr(v381.importlib, "import_module", fake_import)
    assert v381._patch_pair_resolver() is True
    assert module._resolve_pair(object(), "ETHUSD:BTNL") == "ETHUSD"
    assert calls == ["ETHUSD"]


def test_install_reasserts_v380_only_after_pair_patch(monkeypatch):
    calls = []
    monkeypatch.setattr(v381, "_patch_pair_resolver", lambda: True)
    monkeypatch.setattr(v381, "_reassert_v380", lambda: calls.append("v380") or True)
    assert v381.install_import_hook() is True
    assert calls == ["v380"]
