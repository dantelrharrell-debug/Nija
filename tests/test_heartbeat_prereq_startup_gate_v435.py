from __future__ import annotations

import os
import threading

from bot.trading_strategy import TradingStrategy


class _DummyStrategy:
    _heartbeat_trade_lock = threading.RLock()
    _heartbeat_trade_success = False
    _heartbeat_trade_completed = False


def test_nonexecution_prereqs_exclude_execution_ready(monkeypatch):
    import bot.readiness_table as readiness_table

    snapshot = {
        "broker_connected": True,
        "balance_hydrated": True,
        "authority_ready": True,
        "capital_ready": True,
        "risk_ready": True,
        "strategy_ready": True,
        "execution_ready": False,
        "nonce_ready": True,
        "bootstrap_ready": True,
        "position_sync_ready": True,
    }
    monkeypatch.setattr(readiness_table, "snapshot", lambda: dict(snapshot))

    obj = _DummyStrategy()
    ready, detail = TradingStrategy._heartbeat_nonexecution_prereqs_ready(obj)
    assert ready is True
    assert detail == "canonical_nonexecution_prereqs_ready"


def test_nonexecution_prereqs_fail_closed_when_nonce_not_ready(monkeypatch):
    import bot.readiness_table as readiness_table

    snapshot = {
        "broker_connected": True,
        "balance_hydrated": True,
        "authority_ready": True,
        "capital_ready": True,
        "risk_ready": True,
        "strategy_ready": True,
        "execution_ready": False,
        "nonce_ready": False,
        "bootstrap_ready": True,
        "position_sync_ready": True,
    }
    monkeypatch.setattr(readiness_table, "snapshot", lambda: dict(snapshot))

    obj = _DummyStrategy()
    ready, detail = TradingStrategy._heartbeat_nonexecution_prereqs_ready(obj)
    assert ready is False
    assert "nonce_ready" in detail


def test_bounded_wait_does_not_consume_attempt_when_prereqs_never_ready(monkeypatch):
    obj = _DummyStrategy()
    monkeypatch.setenv("NIJA_HEARTBEAT_PREREQ_WAIT_S", "0")
    monkeypatch.setattr(
        obj,
        "_heartbeat_nonexecution_prereqs_ready",
        lambda: (False, "pending:authority_ready"),
        raising=False,
    )
    ready, detail = TradingStrategy._wait_for_heartbeat_nonexecution_prereqs(obj)
    assert ready is False
    assert detail == "pending:authority_ready"
