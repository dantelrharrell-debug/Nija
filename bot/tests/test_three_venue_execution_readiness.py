from __future__ import annotations

import importlib
import os
from types import SimpleNamespace


class FakeBroker:
    def __init__(self, balance: float = 25.0, connected: bool = True) -> None:
        self.connected = connected
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


def test_missing_one_stage_keeps_only_that_venue_fail_closed(monkeypatch) -> None:
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


def test_one_ready_venue_enables_execution_independently(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("CAPITAL_SYSTEM_READY", "1")

    kraken = FakeBroker(balance=116.09)
    manager = SimpleNamespace(
        _platform_brokers={"kraken": kraken},
        eligible_brokers={kraken},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)
    monkeypatch.setattr(module, "_runtime", lambda: (broker_module, manager))

    result = module.evaluate_all()

    assert result["execution_ready"] is True
    assert result["three_venue_execution_ready"] is True
    assert result["any_venue_ready"] is True
    assert result["all_venues_ready"] is False
    assert result["ready_venues"] == ["kraken"]
    assert result["degraded_venues"] == ["coinbase", "okx"]
    assert result["venues"]["kraken"]["ready"] is True
    assert result["venues"]["coinbase"]["ready"] is False
    assert result["venues"]["okx"]["ready"] is False


def test_publish_sets_independent_compatibility_flags(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "evaluate_all",
        lambda: {
            "marker": module.MARKER,
            "timestamp": 1.0,
            "pid": 1,
            "writer_ready": True,
            "capital_ready": True,
            "any_venue_ready": True,
            "all_venues_ready": False,
            "execution_ready": True,
            "three_venue_execution_ready": True,
            "ready_venues": ["kraken"],
            "degraded_venues": ["coinbase", "okx"],
            "venues": {
                "kraken": {
                    "credentials_loaded": True,
                    "authentication_succeeded": True,
                    "balance_fetched": True,
                    "market_metadata_loaded": True,
                    "order_adapter_initialized": True,
                    "venue_marked_ready": True,
                    "eligible_for_execution": True,
                    "spendable_quote": 116.09,
                    "activation_state": "ready",
                    "reason": "ready",
                    "ready": True,
                },
                "coinbase": {
                    "credentials_loaded": True,
                    "authentication_succeeded": False,
                    "balance_fetched": False,
                    "market_metadata_loaded": False,
                    "order_adapter_initialized": True,
                    "venue_marked_ready": False,
                    "eligible_for_execution": False,
                    "spendable_quote": 0.0,
                    "activation_state": "connect_failed",
                    "reason": "not_connected",
                    "ready": False,
                },
                "okx": {
                    "credentials_loaded": True,
                    "authentication_succeeded": False,
                    "balance_fetched": False,
                    "market_metadata_loaded": False,
                    "order_adapter_initialized": True,
                    "venue_marked_ready": False,
                    "eligible_for_execution": False,
                    "spendable_quote": 0.0,
                    "activation_state": "connect_failed",
                    "reason": "not_connected",
                    "ready": False,
                },
            },
        },
    )
    monkeypatch.setattr(module, "_write_state", lambda payload: None)
    monkeypatch.setattr(module, "_LAST_SIGNATURE", "")

    result = module.publish_once(force=True)

    assert result["execution_ready"] is True
    assert os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] == "1"
    assert os.environ["NIJA_ANY_VENUE_EXECUTION_READY"] == "1"
    assert os.environ["NIJA_EXECUTION_READY_VENUES"] == "kraken"
    assert os.environ["NIJA_EXECUTION_DEGRADED_VENUES"] == "coinbase,okx"


def test_source_bootstrap_installs_definitive_verifier() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "source_runtime_guard_bootstrap.py").read_text(encoding="utf-8")

    assert '_install_required("three_venue_execution_readiness")' in source
    assert 'NIJA_THREE_VENUE_STAGE_VERIFIER_INSTALLED' in source
    assert 'three_venue_stage_verifier=installed' in source


def test_ready_contract_contains_independent_summary_marker() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "three_venue_execution_readiness.py").read_text(encoding="utf-8")

    assert "BROKER_INDEPENDENT_EXECUTION_%s" in source
    assert "THREE_VENUE_EXECUTION_%s" in source
    assert "THREE_VENUE_STAGE venue=%s" in source
    assert 'NIJA_THREE_VENUE_EXECUTION_READY' in source
    assert 'NIJA_ANY_VENUE_EXECUTION_READY' in source
    assert 'NIJA_EXECUTION_READY_VENUES' in source
    assert 'ready_venues' in source
    assert 'degraded_venues' in source
