from __future__ import annotations

import importlib
import os
import sys
from types import ModuleType
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


def _set_writer_ready_env(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "7")
    monkeypatch.setenv("NIJA_WRITER_STATE", "ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "9999999999")
    monkeypatch.setenv("NIJA_CORE_THREAD_ALIVE", "1")


def _set_canonical_writer_ready(monkeypatch, module) -> None:
    """Isolate venue tests from process-global writer singleton history.

    Writer authority itself is covered by dedicated fencing/heartbeat tests. Venue
    tests should vary broker readiness while holding the upstream writer gate at a
    known-good canonical state.
    """
    _set_writer_ready_env(monkeypatch)
    monkeypatch.setattr(
        module,
        "writer_authority_snapshot",
        lambda **_kwargs: {
            "ready": True,
            "writer_state": "ACTIVE",
            "lease_acquired": True,
            "fencing_token": True,
            "heartbeat_healthy": True,
            "core_loop_alive": True,
        },
    )


def _published_venue(*, ready: bool, activation_state: str) -> dict[str, object]:
    return {
        "ready": ready,
        "credentials_loaded": True,
        "authentication_succeeded": ready,
        "balance_fetched": ready,
        "market_metadata_loaded": ready,
        "order_adapter_initialized": ready,
        "venue_marked_ready": ready,
        "eligible_for_execution": ready,
        "spendable_quote": 25.0 if ready else 0.0,
        "activation_state": activation_state,
        "reason": "ready" if ready else "not_execution_eligible",
    }


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
    _set_canonical_writer_ready(monkeypatch, module)
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
    assert result["venues"]["kraken"]["activation_state"] == "ready"
    assert result["venues"]["coinbase"]["ready"] is False
    assert result["venues"]["okx"]["ready"] is False


def test_hydrated_fresh_capital_authority_satisfies_capital_gate(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    monkeypatch.delenv("CAPITAL_SYSTEM_READY", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_READY", raising=False)
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_PENDING_CONFIRMATION")
    _set_canonical_writer_ready(monkeypatch, module)

    authority = SimpleNamespace(
        is_hydrated=True,
        is_stale=lambda: False,
        get_real_capital=lambda: 116.09,
    )
    capital_module = ModuleType("bot.capital_authority")
    capital_module.get_capital_authority = lambda: authority
    monkeypatch.setitem(sys.modules, "bot.capital_authority", capital_module)
    monkeypatch.delitem(sys.modules, "capital_authority", raising=False)

    kraken = FakeBroker(balance=116.09)
    manager = SimpleNamespace(
        _platform_brokers={"kraken": kraken},
        eligible_brokers={kraken},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)
    monkeypatch.setattr(module, "_runtime", lambda: (broker_module, manager))

    result = module.evaluate_all()

    assert result["capital_ready"] is True
    assert result["execution_ready"] is True


def test_handoff_corroboration_clears_stale_capital_snapshot(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    monkeypatch.delenv("CAPITAL_SYSTEM_READY", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_READY", raising=False)
    monkeypatch.setenv("NIJA_CAPITAL_READINESS_HANDOFF_V34", "1")
    _set_canonical_writer_ready(monkeypatch, module)

    authority = SimpleNamespace(
        is_hydrated=lambda: True,
        is_stale=lambda *_args, **_kwargs: True,
        get_real_capital=lambda: 116.09,
        valid_brokers=2,
    )
    capital_module = ModuleType("bot.capital_authority")
    capital_module.get_capital_authority = lambda: authority
    monkeypatch.setitem(sys.modules, "bot.capital_authority", capital_module)
    monkeypatch.delitem(sys.modules, "capital_authority", raising=False)

    kraken = FakeBroker(balance=116.09)
    manager = SimpleNamespace(
        _platform_brokers={"kraken": kraken},
        eligible_brokers={kraken},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)
    monkeypatch.setattr(module, "_runtime", lambda: (broker_module, manager))

    result = module.evaluate_all()

    assert result["capital_ready"] is True
    assert result["execution_ready"] is True


def test_publish_once_retains_independent_any_ready_semantics(monkeypatch, tmp_path) -> None:
    module = _module()
    monkeypatch.setattr(module, "_STATE_FILE", tmp_path / "readiness.json")
    monkeypatch.setattr(
        module,
        "evaluate_all",
        lambda: {
            "writer_ready": True,
            "capital_ready": True,
            "execution_ready": True,
            "three_venue_execution_ready": True,
            "any_venue_ready": True,
            "all_venues_ready": False,
            "ready_venues": ["kraken"],
            "degraded_venues": ["coinbase", "okx"],
            "venues": {
                "kraken": _published_venue(ready=True, activation_state="ready"),
                "coinbase": _published_venue(ready=False, activation_state="not_ready"),
                "okx": _published_venue(ready=False, activation_state="not_ready"),
            },
        },
    )

    payload = module.publish_once(force=True)

    assert payload["execution_ready"] is True
    assert os.environ["NIJA_THREE_VENUE_EXECUTION_READY"] == "1"
    assert os.environ["NIJA_ANY_VENUE_EXECUTION_READY"] == "1"
    assert os.environ["NIJA_EXECUTION_READY_VENUES"] == "kraken"
    assert os.environ["NIJA_EXECUTION_DEGRADED_VENUES"] == "coinbase,okx"


def test_okx_authenticated_snapshot_can_satisfy_balance_stage(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    monkeypatch.setenv("NIJA_OKX_BALANCE_OBSERVED", "1")
    monkeypatch.setenv("NIJA_OKX_FUNDING_STATUS", "funded")
    monkeypatch.setenv("NIJA_OKX_TRADING_SPENDABLE_QUOTE", "144.96")

    class OkxBroker(FakeBroker):
        def get_account_balance(self):
            raise AssertionError("authenticated OKX snapshot should avoid another balance request")

    broker = OkxBroker(balance=0.0)
    manager = SimpleNamespace(
        _platform_brokers={"okx": broker},
        eligible_brokers={broker},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)

    row = module.evaluate_venue("okx", broker_module, manager)

    assert row.balance_fetched is True
    assert row.spendable_quote == 144.96
    assert row.venue_marked_ready is True
    assert row.ready is True


def test_okx_unfunded_snapshot_remains_fail_closed(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    monkeypatch.setenv("NIJA_OKX_BALANCE_OBSERVED", "1")
    monkeypatch.setenv("NIJA_OKX_FUNDING_STATUS", "unfunded")
    monkeypatch.setenv("NIJA_OKX_TRADING_SPENDABLE_QUOTE", "0")
    monkeypatch.setenv("NIJA_OKX_ACTIVATION_STATE", "ready")
    monkeypatch.setenv("NIJA_OKX_TRADING_READY", "1")

    broker = FakeBroker(balance=0.0)
    manager = SimpleNamespace(
        _platform_brokers={"okx": broker},
        eligible_brokers={broker},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)

    row = module.evaluate_venue("okx", broker_module, manager)

    assert row.balance_fetched is False
    assert row.eligible_for_execution is False
    assert row.ready is False
    assert "no_spendable_quote" in row.reason


def test_degraded_secondary_does_not_disable_ready_kraken(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    _set_canonical_writer_ready(monkeypatch, module)
    monkeypatch.setenv("CAPITAL_SYSTEM_READY", "1")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "credential_quarantined")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "0")
    monkeypatch.setenv("NIJA_OKX_ACTIVATION_STATE", "credential_quarantined")
    monkeypatch.setenv("NIJA_OKX_TRADING_READY", "0")

    kraken = FakeBroker(balance=116.09)
    coinbase = FakeBroker(balance=95.0, connected=False)
    okx = FakeBroker(balance=144.0, connected=False)
    manager = SimpleNamespace(
        _platform_brokers={"kraken": kraken, "coinbase": coinbase, "okx": okx},
        eligible_brokers={kraken},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)
    monkeypatch.setattr(module, "_runtime", lambda: (broker_module, manager))

    result = module.evaluate_all()

    assert result["execution_ready"] is True
    assert result["ready_venues"] == ["kraken"]
    assert result["venues"]["kraken"]["ready"] is True
    assert result["venues"]["coinbase"]["ready"] is False
    assert result["venues"]["okx"]["ready"] is False


def test_no_ready_venues_keeps_execution_fail_closed(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    _set_canonical_writer_ready(monkeypatch, module)
    monkeypatch.setenv("CAPITAL_SYSTEM_READY", "1")

    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)
    manager = SimpleNamespace(_platform_brokers={}, eligible_brokers=set())
    monkeypatch.setattr(module, "_runtime", lambda: (broker_module, manager))

    result = module.evaluate_all()

    assert result["execution_ready"] is False
    assert result["any_venue_ready"] is False
    assert result["ready_venues"] == []
    assert result["degraded_venues"] == ["kraken", "coinbase", "okx"]


def test_writer_not_ready_keeps_execution_fail_closed(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    monkeypatch.setenv("CAPITAL_SYSTEM_READY", "1")
    monkeypatch.setattr(
        module,
        "writer_authority_snapshot",
        lambda **_kwargs: {"ready": False},
    )

    kraken = FakeBroker(balance=116.09)
    manager = SimpleNamespace(
        _platform_brokers={"kraken": kraken},
        eligible_brokers={kraken},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)
    monkeypatch.setattr(module, "_runtime", lambda: (broker_module, manager))

    result = module.evaluate_all()

    assert result["writer_ready"] is False
    assert result["execution_ready"] is False


def test_unfunded_capital_keeps_execution_fail_closed(monkeypatch) -> None:
    module = _module()
    _set_credentials(monkeypatch)
    _set_canonical_writer_ready(monkeypatch, module)
    monkeypatch.delenv("CAPITAL_SYSTEM_READY", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_READY", raising=False)

    kraken = FakeBroker(balance=116.09)
    manager = SimpleNamespace(
        _platform_brokers={"kraken": kraken},
        eligible_brokers={kraken},
    )
    broker_module = SimpleNamespace(BrokerType=FakeBrokerType)
    monkeypatch.setattr(module, "_runtime", lambda: (broker_module, manager))

    result = module.evaluate_all()

    assert result["capital_ready"] is False
    assert result["execution_ready"] is False
