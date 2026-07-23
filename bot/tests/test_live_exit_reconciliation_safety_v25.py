from __future__ import annotations

import importlib
import time
from types import SimpleNamespace

import pytest


@pytest.fixture()
def modules(monkeypatch):
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    monkeypatch.setenv("NIJA_LIVE_BROKER_PROFIT_EXIT_V25_ENABLED", "false")
    broker_v25 = importlib.import_module("bot.live_broker_profit_exit_convergence_v25")
    engine_v25 = importlib.import_module("bot.live_engine_profit_exit_convergence_v25")
    safety = importlib.import_module("bot.live_exit_reconciliation_safety_v25")
    broker_v25._PENDING.clear()
    engine_v25._PENDING.clear()
    return broker_v25, engine_v25, safety


def test_partial_fill_is_not_full_fill(modules):
    _, _, safety = modules
    assert safety._full_fill_confirmed(
        {"status": "partially_filled", "filled_size": 0.4},
        1.0,
    ) is False
    assert safety._full_fill_confirmed(
        {"status": "open", "filled_size": 1.0},
        1.0,
    ) is True
    assert safety._full_fill_confirmed(
        {"status": "filled", "filled_size": 0.0},
        1.0,
    ) is True


def test_broker_partial_fill_keeps_position_open(modules):
    broker_v25, _, safety = modules
    closed = []
    broker = SimpleNamespace(
        broker_type=SimpleNamespace(value="kraken"),
        account_id="platform",
    )
    pending = broker_v25.PendingExit(
        broker=broker,
        position={
            "position_id": "p1",
            "symbol": "BTC-USD",
            "side": "long",
            "entry_price": 100.0,
            "quantity": 1.0,
        },
        order={"order_id": "o1", "status": "accepted"},
        reason="take_profit_1",
        market=103.0,
        created_at=time.monotonic(),
        deadline=time.monotonic() + 30,
    )
    original = safety.supervisor._mark_closed
    safety.supervisor._mark_closed = lambda *args, **kwargs: closed.append((args, kwargs))
    try:
        assert safety._broker_confirm_and_close(
            pending,
            {"order_id": "o1", "status": "partially_filled", "filled_size": 0.25},
        ) is False
        assert closed == []
    finally:
        safety.supervisor._mark_closed = original


def test_unknown_order_deadline_is_extended_before_original_scan(modules, monkeypatch):
    broker_v25, _, safety = modules
    broker = SimpleNamespace(
        broker_type=SimpleNamespace(value="coinbase"),
        account_id="platform",
    )
    pending = broker_v25.PendingExit(
        broker=broker,
        position={"position_id": "p2", "symbol": "ETH-USD", "quantity": 1.0},
        order={"order_id": "o2", "status": "accepted"},
        reason="take_profit_1",
        market=103.0,
        created_at=time.monotonic() - 60,
        deadline=time.monotonic() - 1,
    )
    broker_v25._PENDING["key"] = pending
    observed = []
    monkeypatch.setattr(safety, "_ORIGINAL_BROKER_SCAN", lambda b: observed.append(pending.deadline) or 0)

    before = time.monotonic()
    assert safety._safe_broker_scan(broker) == 0
    assert observed and observed[0] > before
    assert broker_v25._PENDING["key"] is pending


def test_install_patches_all_exit_paths(modules, monkeypatch):
    broker_v25, engine_v25, safety = modules
    monkeypatch.setattr(safety, "_INSTALLED", False)

    assert safety.install_import_hook() is True
    assert broker_v25._confirm_and_close is safety._broker_confirm_and_close
    assert broker_v25._scan_broker is safety._safe_broker_scan
    assert safety.supervisor._scan_broker is safety._safe_broker_scan
    assert engine_v25._mark_engine_closed is safety._engine_mark_closed
