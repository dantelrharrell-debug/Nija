from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "kraken_profit_realization_guard_under_test",
        BOT_DIR / "kraken_profit_realization_guard_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_thresholds_include_slippage_reserve_and_minimum_net_profit(monkeypatch):
    guard = _load()
    monkeypatch.setenv("NIJA_KRAKEN_EXIT_SLIPPAGE_RESERVE_PCT", "0.0015")
    monkeypatch.setenv("NIJA_KRAKEN_MIN_REALIZED_NET_PROFIT_PCT", "0.004")
    fake = SimpleNamespace(
        __name__="bot.kraken_all_account_exit_runtime_patch",
        _exit_thresholds=lambda account, symbol, entry: (entry * 1.008, entry * 1.012),
    )
    assert guard._patch_thresholds(fake) is True
    breakeven, target = fake._exit_thresholds("platform", "SOL-USD", 100.0)
    assert abs(breakeven - 100.95) < 1e-9
    assert abs(target - 101.35) < 1e-9


def test_explicit_take_profit_below_net_floor_is_suppressed():
    guard = _load()
    fake = SimpleNamespace(
        __name__="bot.kraken_all_account_exit_runtime_patch",
        _exit_reason=lambda position, price, account, symbol: ("take_profit", 100.95, 101.35),
    )
    assert guard._patch_exit_reason(fake) is True
    reason, breakeven, target = fake._exit_reason(
        {"side": "long", "cost_basis_verified": True},
        101.10,
        "platform",
        "SOL-USD",
    )
    assert reason is None
    assert breakeven == 100.95
    assert target == 101.35


def test_explicit_take_profit_at_net_floor_is_allowed():
    guard = _load()
    fake = SimpleNamespace(
        __name__="bot.kraken_all_account_exit_runtime_patch",
        _exit_reason=lambda position, price, account, symbol: ("take_profit_1", 100.95, 101.35),
    )
    assert guard._patch_exit_reason(fake) is True
    reason, _, _ = fake._exit_reason(
        {"side": "long", "cost_basis_verified": True},
        101.35,
        "platform",
        "SOL-USD",
    )
    assert reason == "take_profit_1"


def test_accepted_order_remains_pending_until_closed():
    guard = _load()

    class Broker:
        def __init__(self):
            self.status = "accepted"

        def get_order_status(self, order_id):
            return {"order_id": order_id, "status": self.status}

    broker = Broker()
    pending = {"order_id": "OID-1"}
    state, _ = guard._pending_confirmation(broker, pending)
    assert state == "pending"
    broker.status = "closed"
    state, _ = guard._pending_confirmation(broker, pending)
    assert state == "confirmed"


def test_emergency_stop_is_never_suppressed():
    guard = _load()
    fake = SimpleNamespace(
        __name__="bot.kraken_all_account_exit_runtime_patch",
        _exit_reason=lambda position, price, account, symbol: ("emergency_stop_loss", 100.95, 101.35),
    )
    assert guard._patch_exit_reason(fake) is True
    reason, _, _ = fake._exit_reason({"side": "long"}, 90.0, "platform", "SOL-USD")
    assert reason == "emergency_stop_loss"
