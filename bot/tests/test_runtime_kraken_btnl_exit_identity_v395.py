from types import SimpleNamespace

from bot import runtime_kraken_btnl_exit_identity_v395_patch as v395


def _openpositions(rows):
    return {"error": [], "result": rows}


def test_discover_btnl_long_aggregates_same_execution_identity(monkeypatch):
    payload = _openpositions({
        "P1": {
            "pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.10", "vol_closed": "0.01",
            "cost": "225", "margin": "112.5",
        },
        "P2": {
            "pair": "ETH/USD:BTNL", "type": "buy", "vol": "0.05", "vol_closed": "0.00257297",
            "cost": "118.5", "margin": "59.25",
        },
    })
    fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)
    monkeypatch.setattr(
        v395.importlib,
        "import_module",
        lambda name: fake_v366 if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch" else None,
    )

    truth = v395._discover_btnl_long(object(), "ETHUSD")

    assert truth["ok"] is True
    assert truth["found"] is True
    assert truth["symbol"] == "ETHUSD:BTNL"
    assert abs(truth["remaining_units"] - 0.13742703) < 1e-12
    assert truth["leverage"] == 2
    assert set(truth["position_ids"]) == {"P1", "P2"}


def test_discover_btnl_long_fails_closed_on_mixed_direction(monkeypatch):
    payload = _openpositions({
        "LONG": {"pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.1", "vol_closed": "0"},
        "SHORT": {"pair": "ETHUSD:BTNL", "type": "sell", "vol": "0.02", "vol_closed": "0"},
    })
    fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)
    monkeypatch.setattr(
        v395.importlib,
        "import_module",
        lambda name: fake_v366 if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch" else None,
    )

    truth = v395._discover_btnl_long(object(), "ETHUSD")

    assert truth["ok"] is False
    assert truth["ambiguous"] is True
    assert truth["reason"] == "mixed_direction_btnl_openpositions"


def test_reference_price_translation_is_read_only():
    class Broker:
        def __init__(self):
            self.calls = []

        def get_current_price(self, symbol):
            self.calls.append(symbol)
            return 2480.0

    broker = Broker()
    assert v395._patch_reference_price_class(broker) is True

    assert broker.get_current_price("ETHUSD:BTNL") == 2480.0
    assert broker.get_current_price("BTCUSD") == 2480.0
    assert broker.calls == ["ETHUSD", "BTCUSD"]


def test_exit_submit_routes_authenticated_btnl_identity_and_caps_quantity(monkeypatch):
    calls = []

    def prior_submit(broker, account, pair, quantity, reason):
        calls.append((account, pair, quantity, reason))
        return {"status": "filled", "filled_size_usd": 100.0}

    setattr(prior_submit, v395._V265_SENTINEL, True)
    fake_exit = SimpleNamespace(_submit_exit=prior_submit)
    payload = _openpositions({
        "P1": {
            "pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.13742703", "vol_closed": "0",
            "cost": "343.38569", "margin": "171.692845",
        }
    })
    fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)

    def importer(name):
        if name == "bot.kraken_all_account_exit_runtime_patch":
            return fake_exit
        if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch":
            return fake_v366
        raise ImportError(name)

    monkeypatch.setattr(v395.importlib, "import_module", importer)

    class Broker:
        def get_current_price(self, symbol):
            return 2480.0

    assert v395._patch_exit_submit() is True
    result = fake_exit._submit_exit(Broker(), "platform:kraken", "ETHUSD", 0.2, "stop_loss")

    assert result["status"] == "filled"
    assert len(calls) == 1
    account, pair, quantity, reason = calls[0]
    assert account == "platform:kraken"
    assert pair == "ETHUSD:BTNL"
    assert abs(quantity - 0.13742703) < 1e-12
    assert reason == "stop_loss"
    assert getattr(fake_exit._submit_exit, v395._V265_SENTINEL) is True


def test_exit_submit_does_not_fall_back_to_spot_when_btnl_is_ambiguous(monkeypatch):
    calls = []

    def prior_submit(*args):
        calls.append(args)
        return {"status": "filled"}

    setattr(prior_submit, v395._V265_SENTINEL, True)
    fake_exit = SimpleNamespace(_submit_exit=prior_submit)
    payload = _openpositions({
        "LONG": {"pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.1", "vol_closed": "0"},
        "SHORT": {"pair": "ETHUSD:BTNL", "type": "sell", "vol": "0.01", "vol_closed": "0"},
    })
    fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)

    def importer(name):
        if name == "bot.kraken_all_account_exit_runtime_patch":
            return fake_exit
        if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch":
            return fake_v366
        raise ImportError(name)

    monkeypatch.setattr(v395.importlib, "import_module", importer)

    assert v395._patch_exit_submit() is True
    result = fake_exit._submit_exit(object(), "platform:kraken", "ETHUSD", 0.1, "stop_loss")

    assert result["status"] == "error"
    assert "mixed_direction_btnl_openpositions" in result["error"]
    assert calls == []


def test_exit_submit_delegates_ordinary_non_margin_exit(monkeypatch):
    calls = []

    def prior_submit(broker, account, pair, quantity, reason):
        calls.append((pair, quantity))
        return {"status": "filled"}

    setattr(prior_submit, v395._V265_SENTINEL, True)
    fake_exit = SimpleNamespace(_submit_exit=prior_submit)
    fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: _openpositions({}))

    def importer(name):
        if name == "bot.kraken_all_account_exit_runtime_patch":
            return fake_exit
        if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch":
            return fake_v366
        raise ImportError(name)

    monkeypatch.setattr(v395.importlib, "import_module", importer)

    assert v395._patch_exit_submit() is True
    result = fake_exit._submit_exit(object(), "platform:kraken", "SOLUSD", 1.0, "profit_target")

    assert result["status"] == "filled"
    assert calls == [("SOLUSD", 1.0)]
