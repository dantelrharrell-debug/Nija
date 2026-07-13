from __future__ import annotations

import importlib.util
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "kraken_equity_dynamic_under_test",
        BOT_DIR / "kraken_equity_runtime_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAPI:
    def __init__(self):
        self.calls = []

    def query_public(self, method, params=None):
        params = dict(params or {})
        self.calls.append((method, params))
        pair = params.get("pair")
        if method == "AssetPairs":
            if pair == "AIREUR":
                return {
                    "error": [],
                    "result": {
                        "AIREUR": {
                            "altname": "AIREUR",
                            "wsname": "AIR/EUR",
                            "quote": "ZEUR",
                        }
                    },
                }
            return {"error": ["EQuery:Unknown asset pair"], "result": {}}
        if method == "Ticker" and pair == "AIREUR":
            return {"error": [], "result": {"AIREUR": {"c": ["0.004", "1"]}}}
        if method == "Ticker" and pair in {"EURUSD", "ZEURZUSD"}:
            return {"error": [], "result": {"EURUSD": {"c": ["1.10", "1"]}}}
        return {"error": ["not mocked"], "result": {}}


class FakeKraken:
    def __init__(self):
        self.api = FakeAPI()


def test_air_falls_back_to_actual_eur_pair_and_converts_to_usd():
    module = _load()
    broker = FakeKraken()
    price, pair, source = module._price_asset(broker, "AIR")
    assert pair == "AIREUR"
    assert source == "kraken_public"
    assert abs(price - 0.0044) < 1e-12
    assert ("AssetPairs", {"pair": "AIRUSD"}) in broker.api.calls
    assert ("AssetPairs", {"pair": "AIREUR"}) in broker.api.calls


def test_dynamic_asset_value_is_included_without_tracker_mutation():
    module = _load()
    broker = FakeKraken()
    positions = module._build_positions(broker, {"AIR": 2901.96202531})
    assert len(positions) == 1
    assert positions[0]["price_pair"] == "AIREUR"
    assert positions[0]["size_usd"] > 12.0
    total = module._payload_total_equity(
        {"result": {"ZUSD": "72.6069"}, "total_funds": 72.6069},
        positions,
    )
    assert total > 85.0
