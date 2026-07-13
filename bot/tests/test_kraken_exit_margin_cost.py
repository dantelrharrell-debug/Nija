from __future__ import annotations

import importlib.util
import types
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patch = load_module(
    "kraken_exit_margin_cost_under_test",
    "kraken_exit_margin_cost_patch.py",
)


def test_user_supervisor_identity_uses_user_margin_ledger_key():
    captured = {}
    module = types.ModuleType("bot.kraken_all_account_exit_runtime_patch")

    def margin_extra_buffer(account, symbol):
        captured["account"] = account
        captured["symbol"] = symbol
        return 0.002

    module._margin_extra_buffer = margin_extra_buffer
    assert patch._patch_exit_runtime(module)
    assert module._margin_extra_buffer("user:tania_gilbert:kraken", "AIR-EUR") == 0.002
    assert captured == {"account": "tania_gilbert", "symbol": "AIR-EUR"}


def test_platform_supervisor_identity_uses_platform_margin_ledger_key():
    captured = {}
    module = types.ModuleType("bot.kraken_all_account_exit_runtime_patch.platform")

    def margin_extra_buffer(account, symbol):
        captured["account"] = account
        return 0.002

    module._margin_extra_buffer = margin_extra_buffer
    assert patch._patch_exit_runtime(module)
    module._margin_extra_buffer("platform:kraken", "SOL-USD")
    assert captured["account"] == "platform"
