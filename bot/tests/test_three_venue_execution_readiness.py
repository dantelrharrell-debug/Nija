from __future__ import annotations

import importlib
import os
from types import SimpleNamespace


class FakeBroker:
    def __init__(self, balance: float = 25.0) -> None:
        self.connected = True
        self._balance = balance

    def get_account_balance(self):
        return self._balance

    def get_available_markets(self):
        return ["BTC-USD", "ETH-USD"]

    def place_market_order(self, *args, **kwargs):
        return {"ok": True}


class FakeBrokerType:
    KRAKEN = "kraken"
    COINBASE = "coinbase"
    OKX = "okx"


def _module():
    return importlib.import_module("three_venue_execution_readiness")


def _set_credentials(monkeypatch) -> None:
    values = {
        "KRAKEN_PLATFORM_API_KEY": "k",
        "KRAKEN_PLATFORM_API_SECRET": "s",
        "COINBASE_API_KEY": "k",
        "COINBASE_API_SECRET": "s",
        "OKX_API_KEY": "k",
        "OKX_API_SECRET": "s",
        "OKX_PASSPHRASE": "p",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_all_three_venues_require_every_stage(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    for venue in ("COINBASE", "OKX"):
        monkeypatch.setenv(f"NIJA_{venue}_ACTIVATION_STATE", "ready")
        monkeypatch.setenv(f"NIJA_{venue}_TRADING_READY", "1")

    brokers = {name: FakeBroker() for name in ("kraken", "coinbase", "okx")}
    manager = SimpleNamespace(
        _platform_brokers=brokers,
        eligible_brokers=set(brokers.values()),
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)

    rows = [module.evaluate_venue(name, broker_module, manager) for name in module.VENUES]

    assert all(row.ready for row in rows)
    for row in rows:
        assert row.credentials_loaded
        assert row.authentication_succeeded
        assert row.balance_fetched
        assert row.market_metadata_loaded
        assert row.order_adapter_initialized
        assert row.venue_marked_ready
        assert row.eligible_for_execution


def test_missing_one_stage_keeps_venue_fail_closed(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "ready")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")

    broker = FakeBroker(balance=0.0)
    manager = SimpleNamespace(_platform_brokers={"coinbase": broker})
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)

    result = module.evaluate_venue("coinbase", broker_module, manager)

    assert result.balance_fetched is False
    assert result.eligible_for_execution is False
    assert result.ready is False
    assert "no_spendable_quote" in result.reason


def test_source_bootstrap_installs_definitive_verifier() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "source_runtime_guard_bootstrap.py").read_text(encoding="utf-8")

    assert '_install_required("three_venue_execution_readiness")' in source
    assert 'NIJA_THREE_VENUE_STAGE_VERIFIER_INSTALLED' in source
    assert 'three_venue_stage_verifier=installed' in source


def test_ready_contract_contains_required_summary_marker() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "three_venue_execution_readiness.py").read_text(encoding="utf-8")

    assert "THREE_VENUE_EXECUTION_%s" in source
    assert "THREE_VENUE_STAGE venue=%s" in source
    assert 'NIJA_THREE_VENUE_EXECUTION_READY' in source
    assert 'credentials_loaded' in source
    assert 'authentication_succeeded' in source
    assert 'balance_fetched' in source
    assert 'market_metadata_loaded' in source
    assert 'order_adapter_initialized' in source
    assert 'venue_marked_ready' in source
    assert 'eligible_for_execution' in source
