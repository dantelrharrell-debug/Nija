"""Regression: strategy Kraken reads must not overwrite authenticated Balance proof."""
from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_authoritative_position_coverage_v285_patch as v285


def test_kraken_strategy_read_preserves_authenticated_snapshot(monkeypatch):
    class KrakenBroker:
        broker_type = "kraken"
        connected = True

        def get_positions(self):
            return []

    class CoinbaseBroker:
        broker_type = "coinbase"
        connected = True

        def get_positions(self):
            return [{"symbol": "BTC-USD", "quantity": 1.0}]

    fake_manager = SimpleNamespace(KrakenBroker=KrakenBroker, CoinbaseBroker=CoinbaseBroker)
    real_import = v285.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "bot.broker_manager":
            return fake_manager
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(v285.importlib, "import_module", fake_import)
    assert v285._patch_broker_get_positions() is True

    kraken = KrakenBroker()
    kraken._nija_authoritative_position_snapshot_generation_v285 = 17
    kraken._nija_authoritative_position_raw_generation_v286 = 17
    kraken._nija_authoritative_position_snapshot_fetch_ok_v285 = True
    assert kraken.get_positions() == []
    assert kraken._nija_authoritative_position_snapshot_generation_v285 == 17
    assert kraken._nija_authoritative_position_raw_generation_v286 == 17
    assert kraken._nija_authoritative_position_snapshot_fetch_ok_v285 is True

    coinbase = CoinbaseBroker()
    assert len(coinbase.get_positions()) == 1
    assert coinbase._nija_authoritative_position_snapshot_generation_v285 == 1


def test_kraken_strategy_exception_remains_fail_closed(monkeypatch):
    class KrakenBroker:
        broker_type = "kraken"
        connected = True

        def get_positions(self):
            raise TimeoutError("authenticated fetch unavailable")

    fake_manager = SimpleNamespace(KrakenBroker=KrakenBroker)
    real_import = v285.importlib.import_module

    def fake_import(name, *args, **kwargs):
        return fake_manager if name == "bot.broker_manager" else real_import(name, *args, **kwargs)

    monkeypatch.setattr(v285.importlib, "import_module", fake_import)
    assert v285._patch_broker_get_positions() is True
    broker = KrakenBroker()
    try:
        broker.get_positions()
    except TimeoutError:
        pass
    else:
        raise AssertionError("fetch failure must propagate")
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
