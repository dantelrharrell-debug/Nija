from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "kraken_exit_only_recovery_guard_under_test",
        BOT_DIR / "kraken_exit_only_recovery_phase_guard_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KrakenBroker:
    broker_type = "kraken"


class CoinbaseBroker:
    broker_type = "coinbase"


def test_kraken_recovery_skips_full_run_cycle_and_calls_direct_exit_scan(monkeypatch):
    module = _load()
    calls = {"original": 0, "exit_scan": 0, "sync": 0, "adopt": 0}

    def original(trader, identity, broker):
        calls["original"] += 1
        return 99, 99

    recovery = SimpleNamespace(
        __name__="account_exit_management_recovery_patch",
        _adopt_and_manage=original,
        _position_count=lambda broker: 2,
        _open_order_count=lambda broker: 0,
    )

    class Strategy:
        def adopt_existing_positions(self, **kwargs):
            calls["adopt"] += 1
            return {"positions_found": 2, "positions_adopted": 2, "open_orders_count": 0}

    trader = SimpleNamespace(trading_strategy=Strategy())
    monkeypatch.setattr(module, "_scan_exits", lambda trader, identity, broker: calls.__setitem__("exit_scan", calls["exit_scan"] + 1) or 1)
    monkeypatch.setattr(module, "_refresh_exact_snapshot", lambda strategy, broker, identity: calls.__setitem__("sync", calls["sync"] + 1))

    assert module._patch_recovery_module(recovery) is True
    positions, orders = recovery._adopt_and_manage(trader, "platform:kraken", KrakenBroker())

    assert positions == 2
    assert orders == 0
    assert calls == {"original": 0, "exit_scan": 1, "sync": 1, "adopt": 1}


def test_non_kraken_recovery_behavior_is_unchanged():
    module = _load()
    calls = {"original": 0}

    def original(trader, identity, broker):
        calls["original"] += 1
        return 3, 4

    recovery = SimpleNamespace(
        __name__="account_exit_management_recovery_patch",
        _adopt_and_manage=original,
        _position_count=lambda broker: 0,
        _open_order_count=lambda broker: 0,
    )
    module._patch_recovery_module(recovery)

    assert recovery._adopt_and_manage(SimpleNamespace(), "platform:coinbase", CoinbaseBroker()) == (3, 4)
    assert calls["original"] == 1
