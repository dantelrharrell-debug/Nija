"""Offline v373 regression: exact Kraken account routing, no inferred owner.

No broker requests, trading orders, ledger writes, or production state changes.
"""
from __future__ import annotations

import importlib
import time
from types import SimpleNamespace

import pytest

from bot import runtime_kraken_margin_execution_readiness_v373_patch as v373


def _proof(**changes):
    payload = {
        "order_id": "ORDER-123",
        "status": "closed",
        "symbol": "BTCUSD",
        "side": "buy",
        "filled_price": 80000.0,
        "filled_quantity": 0.01,
        "broker": "kraken",
        "recovered_fill_proof": True,
        "authenticated_kraken_queryorders": True,
        "broker_fill_at_epoch": 1788800000.0,
    }
    payload.update(changes)
    return payload


def _run(monkeypatch, account, proof):
    accepted = []
    wake_calls = []
    broker = object()
    candidate = {"order_id": "ORDER-123"}
    v367 = SimpleNamespace(
        _account_brokers=lambda: [(account, broker)],
        _private_call=lambda item: (lambda _endpoint, _params: {}),
    )
    v372 = SimpleNamespace(
        _candidate_opening_orders=lambda scope, item: ([candidate], "ok"),
        _exact_queryorders_fill=lambda call, item: (proof, "ok"),
        _log_due=lambda _key, interval_s=30.0: True,
    )
    monkeypatch.setattr(v373, "_canonical_execution_ready", lambda: False)
    monkeypatch.setattr(v373, "_ensure_v169_ready", lambda: (True, "ready"))
    monkeypatch.setattr(v373, "_v367", lambda: v367)
    monkeypatch.setattr(v373, "_v372", lambda: v372)

    original_import = importlib.import_module

    def isolated_import(name):
        if name == "bot.runtime_confirmed_fill_profitability_v328_patch":
            def normalize(result, *, symbol, side):
                accepted.append((dict(result), symbol, side))
                return result["filled_price"], result["filled_quantity"] * result["filled_price"]
            return SimpleNamespace(_normalize_dict_fill=normalize)
        if name == "bot.runtime_execution_position_readiness_v346_patch":
            return SimpleNamespace(
                _wake_activation_after_proof=lambda: wake_calls.append("activation"),
                _wake_position_sync=lambda: wake_calls.append("sync"),
            )
        return original_import(name)

    monkeypatch.setattr(v373.importlib, "import_module", isolated_import)
    result = v373.recover_execution_proof_once()
    return result, accepted, wake_calls


@pytest.mark.parametrize("account", [
    "platform:kraken",
    "user:test_customer:kraken",
])
def test_exact_authenticated_account_preserved(monkeypatch, account):
    result, accepted, wake = _run(monkeypatch, account, _proof())
    assert result == 1
    assert len(accepted) == 1
    payload, symbol, side = accepted[0]
    assert payload["account"] == payload["account_id"] == account
    assert payload["broker"] == "kraken"
    assert payload["recovered_fill_proof"] is True
    assert (symbol, side) == ("BTCUSD", "buy")
    assert wake == ["activation", "sync"]


@pytest.mark.parametrize("account", [
    "",
    "platform",
    "user::kraken",
    "user:a:b:kraken",
    "kraken",
])
def test_unknown_or_ambiguous_account_does_not_reach_fill_chain(monkeypatch, account):
    result, accepted, wake = _run(monkeypatch, account, _proof())
    assert result == 0
    assert accepted == []
    assert wake == []


@pytest.mark.parametrize("conflict", [
    {"account": "user:other:kraken"},
    {"account_id": "user:other:kraken"},
    {"broker": "coinbase"},
])
def test_conflicting_provenance_is_rejected(monkeypatch, conflict):
    result, accepted, wake = _run(monkeypatch, "platform:kraken", _proof(**conflict))
    assert result == 0
    assert accepted == []
    assert wake == []


def test_queryorders_no_proof_never_promotes(monkeypatch):
    result, accepted, wake = _run(monkeypatch, "platform:kraken", None)
    assert result == 0
    assert accepted == []
    assert wake == []


@pytest.mark.parametrize("invalid", [
    {"order_id": "OTHER-ORDER"},
    {"recovered_fill_proof": False},
    {"authenticated_kraken_queryorders": False},
    {"broker_fill_at_epoch": None},
    {"broker_fill_at_epoch": float("nan")},
    {"broker_fill_at_epoch": float("inf")},
    {"broker_fill_at_epoch": time.time() + 3600},
])
def test_historical_fill_must_keep_exact_exchange_provenance(monkeypatch, invalid):
    result, accepted, wake = _run(
        monkeypatch, "platform:kraken", _proof(**invalid)
    )
    assert result == 0
    assert accepted == []
    assert wake == []
