from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


BOT_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harvest = _load("daily_gain_profit_harvest_under_test", "daily_gain_profit_harvest_patch.py")


class Runtime:
    @staticmethod
    def _entry_price(position):
        return float(position.get("entry_price") or 0.0)

    @staticmethod
    def _exit_thresholds(account, symbol, entry):
        return entry * 1.008, entry * 1.012


def test_long_daily_gain_harvest_requires_lifetime_net_profit(monkeypatch):
    monkeypatch.setenv("NIJA_DAILY_GAIN_HARVEST_ENABLED", "true")
    monkeypatch.setenv("NIJA_DAILY_GAIN_HARVEST_PCT", "0.006")

    profitable = {
        "side": "long",
        "entry_price": 100.0,
        "daily_open_price": 100.5,
    }
    reason, daily_gain = harvest._daily_harvest_reason(
        Runtime, profitable, 101.2, "platform:kraken", "SOL-USD"
    )
    assert reason == "daily_gain_harvest"
    assert daily_gain > 0.006

    overall_loser = {
        "side": "long",
        "entry_price": 110.0,
        "daily_open_price": 100.0,
    }
    reason, daily_gain = harvest._daily_harvest_reason(
        Runtime, overall_loser, 101.0, "platform:kraken", "SOL-USD"
    )
    assert reason is None
    assert daily_gain == 0.01


def test_short_daily_gain_harvest_requires_lifetime_net_profit(monkeypatch):
    monkeypatch.setenv("NIJA_DAILY_GAIN_HARVEST_ENABLED", "true")
    monkeypatch.setenv("NIJA_DAILY_GAIN_HARVEST_PCT", "0.006")

    position = {
        "side": "short",
        "entry_price": 100.0,
        "daily_open_price": 99.5,
    }
    reason, daily_gain = harvest._daily_harvest_reason(
        Runtime, position, 98.8, "user:daivon:kraken", "SOL-USD"
    )
    assert reason == "daily_gain_harvest"
    assert daily_gain > 0.006


def test_missing_cost_basis_never_sells_intraday_bounce(monkeypatch):
    monkeypatch.setenv("NIJA_DAILY_GAIN_HARVEST_ENABLED", "true")
    monkeypatch.setenv("NIJA_DAILY_GAIN_HARVEST_PCT", "0.006")
    position = {
        "side": "long",
        "entry_price": 0.0,
        "daily_open_price": 100.0,
    }
    reason, daily_gain = harvest._daily_harvest_reason(
        Runtime, position, 102.0, "user:tania:kraken", "SOL-USD"
    )
    assert reason is None
    assert daily_gain == 0.0


def test_existing_stronger_exit_reason_is_preserved(monkeypatch):
    runtime = SimpleNamespace()
    runtime._position_rows = lambda broker: []
    runtime._normalise_symbol = lambda value: str(value)
    runtime._resolve_pair = lambda broker, symbol: symbol
    runtime._entry_price = lambda position: float(position.get("entry_price") or 0.0)
    runtime._exit_thresholds = lambda account, symbol, entry: (entry * 1.008, entry * 1.012)
    runtime._exit_reason = lambda position, price, account, symbol: (
        "take_profit_1", 100.8, 101.2
    )

    assert harvest._patch_runtime(runtime) is True
    reason, breakeven, target = runtime._exit_reason(
        {"entry_price": 100.0, "daily_open_price": 100.0},
        102.0,
        "platform:kraken",
        "SOL-USD",
    )
    assert reason == "take_profit_1"
    assert breakeven == 100.8
    assert target == 101.2
