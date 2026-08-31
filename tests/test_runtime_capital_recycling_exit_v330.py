from __future__ import annotations

from types import SimpleNamespace


def _fake_floor_module():
    return SimpleNamespace(
        _floors=lambda universal, broker, pos: (
            101.0,
            105.0,
            {
                "break_even": 101.0,
                "net_target": 105.0,
                "short": False,
                "round_trip": 0.01,
                "slippage": 0.0,
                "minimum_net": 0.04,
            },
        )
    )


class _Broker:
    broker_type = "coinbase"

    def __init__(self, balance: float):
        self._last_known_balance = balance


def test_capital_starvation_collapses_exit_to_true_break_even(monkeypatch):
    from bot import runtime_capital_recycling_exit_v330_patch as v330

    monkeypatch.setenv("NIJA_CAPITAL_RECYCLE_COINBASE_RESERVE_USD", "14.50")
    broker = _Broker(8.39)
    pos = {"entry_time": "2026-08-31T20:00:00+00:00"}

    target, reason, details = v330._recycle_target(
        _fake_floor_module(), SimpleNamespace(), broker, pos
    )

    assert reason == "capital_recycle_break_even"
    assert target == 101.0
    assert details["capital_starved"] is True
    assert details["reserve_usd"] == 14.50


def test_aged_position_target_decays_toward_break_even(monkeypatch):
    from bot import runtime_capital_recycling_exit_v330_patch as v330

    monkeypatch.setenv("NIJA_CAPITAL_RECYCLE_COINBASE_RESERVE_USD", "14.50")
    monkeypatch.setenv("NIJA_CAPITAL_RECYCLE_DECAY_START_MIN", "60")
    monkeypatch.setenv("NIJA_CAPITAL_RECYCLE_FULL_DECAY_MIN", "180")
    broker = _Broker(100.0)

    monkeypatch.setattr(v330, "_held_minutes", lambda pos: 120.0)
    target, reason, details = v330._recycle_target(
        _fake_floor_module(), SimpleNamespace(), broker, {}
    )

    assert reason == "aged_profit_target_decay"
    assert 101.0 < target < 105.0
    assert abs(target - 103.0) < 1e-9
    assert details["capital_starved"] is False


def test_fresh_position_keeps_normal_profit_window(monkeypatch):
    from bot import runtime_capital_recycling_exit_v330_patch as v330

    broker = _Broker(100.0)
    monkeypatch.setattr(v330, "_held_minutes", lambda pos: 15.0)
    target, reason, details = v330._recycle_target(
        _fake_floor_module(), SimpleNamespace(), broker, {}
    )

    assert target == 0.0
    assert reason == "normal_profit_window"
    assert details["capital_starved"] is False


def test_jit_kraken_quantity_reuses_authenticated_balance(monkeypatch):
    from bot import runtime_capital_recycling_exit_v330_patch as v330

    broker = SimpleNamespace(broker_type="kraken")
    monkeypatch.setattr(
        v330,
        "_kraken_recent_balance_quantities",
        lambda _broker: ({"ETH-USD": 0.09565438}, "v312_authenticated_balance"),
    )

    ok, qty, source, age = v330._jit_quantity(broker, "ETH/USD")

    assert ok is True
    assert abs(qty - 0.09565438) < 1e-12
    assert source == "v312_authenticated_balance"
    assert age == 0.0


def test_entry_reserve_blocks_trade_that_consumes_last_free_cash(monkeypatch):
    from bot import live_entry_expectancy_authority_v69_patch as v69
    from bot import runtime_capital_recycling_exit_v330_patch as v330

    monkeypatch.setenv("NIJA_CAPITAL_RECYCLE_COINBASE_RESERVE_USD", "14.50")
    monkeypatch.setattr(
        v69,
        "_validate_live_entry",
        lambda strategy, df, symbol, result: (True, "expectancy_authority_pass", {}),
    )
    assert v330._patch_entry_reserve() is True

    broker = _Broker(20.0)
    strategy = SimpleNamespace(broker_client=broker)
    ok, reason, details = v69._validate_live_entry(
        strategy,
        None,
        "BTC-USD",
        {"action": "enter_long", "size_usd": 10.0},
    )

    assert ok is False
    assert reason == "entry_would_consume_capital_reserve"
    assert details["free_balance"] == 20.0
    assert details["capital_reserve_usd"] == 14.50
    assert details["post_entry_free_balance"] == 10.0
