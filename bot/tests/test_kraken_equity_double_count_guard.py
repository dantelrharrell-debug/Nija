from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exchange_equity_reader_ignores_synthetic_total_funds():
    guard = _load("kraken_equity_guard_under_test", "kraken_equity_double_count_guard_patch.py")
    payload = {
        "total_funds": 104.3227,
        "usd_held": 15.7872,
        "result": {"eb": "93.2666", "e": "77.4794"},
    }
    assert abs(guard._exchange_equity(payload) - 93.2666) < 1e-9


def test_canonical_equity_does_not_add_held_value_to_crypto_twice():
    guard = _load("kraken_equity_guard_canonical_under_test", "kraken_equity_double_count_guard_patch.py")

    fake_equity = types.ModuleType("bot.kraken_equity_runtime_patch")
    fake_equity._call_balance_payload = lambda instance, allow_live_probe=False: {
        "result": {"ZUSD": "72.6069", "eb": "93.2666", "e": "77.4794"},
        "usd_held": 15.7872,
        "total_funds": 104.3227,
    }
    fake_equity._extract_raw_balances = lambda payload: {"AIR": 2901.96202531}
    fake_equity._build_positions = lambda instance, assets: [{"size_usd": 15.9286}]
    fake_equity._cash_from_payload = lambda payload: 72.6069

    fake_bot = types.ModuleType("bot")
    fake_bot.kraken_equity_runtime_patch = fake_equity
    old_bot = sys.modules.get("bot")
    old_equity = sys.modules.get("bot.kraken_equity_runtime_patch")
    try:
        sys.modules["bot"] = fake_bot
        sys.modules["bot.kraken_equity_runtime_patch"] = fake_equity
        total, exchange, cash, crypto = guard._canonical(object(), 104.3227)
    finally:
        if old_bot is None:
            sys.modules.pop("bot", None)
        else:
            sys.modules["bot"] = old_bot
        if old_equity is None:
            sys.modules.pop("bot.kraken_equity_runtime_patch", None)
        else:
            sys.modules["bot.kraken_equity_runtime_patch"] = old_equity

    assert abs(exchange - 93.2666) < 1e-9
    assert abs(cash - 72.6069) < 1e-9
    assert abs(crypto - 15.9286) < 1e-9
    assert abs(total - 93.2666) < 1e-9
    assert total < 104.3227
