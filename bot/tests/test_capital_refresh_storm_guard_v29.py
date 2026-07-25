from __future__ import annotations

import logging
import sys
from types import ModuleType, SimpleNamespace

import kraken_equity_freshness_v3_patch as freshness
from bot import activation_pending_commit_monitor_patch as activation
from bot import capital_authority_live_total_v2_patch as live_total
from bot import runtime_authority_convergence_repair_patch as convergence


class _Broker:
    connected = True

    def __init__(self, cached=226.62):
        self._last_known_balance = cached
        self.live_calls = 0

    def get_account_balance(self):
        self.live_calls += 1
        raise AssertionError("startup monitor must not call private balance API")


class _Manager:
    def __init__(self, broker):
        self._platform_brokers = {"kraken": broker}

    def is_platform_connected(self, _broker_type):
        return True


class _CapitalAuthority:
    def __init__(self, balance=226.62):
        self._broker_balances = {"kraken": balance} if balance else {}
        self.feed_calls = 0

    def force_accept_feed(self, *_args, **_kwargs):
        self.feed_calls += 1
        raise AssertionError("startup monitor must not republish capital feed")


def _install_cached_modules(monkeypatch, broker, capital_authority):
    manager_module = ModuleType("bot.multi_account_broker_manager")
    manager_module.get_broker_manager = lambda: _Manager(broker)
    capital_module = ModuleType("bot.capital_authority")
    capital_module.get_capital_authority = lambda: capital_authority
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", manager_module)
    monkeypatch.setitem(sys.modules, "bot.capital_authority", capital_module)


def test_runtime_convergence_uses_cached_balance_without_private_io(monkeypatch):
    broker = _Broker(cached={"total_funds": 226.62})
    capital_authority = _CapitalAuthority()
    _install_cached_modules(monkeypatch, broker, capital_authority)

    payload = convergence._broker_manager_capital_payload()

    assert payload["source"] == "cached_only"
    assert payload["connected_count"] == 1
    assert payload["total_balance"] == 226.62
    assert payload["per_broker"] == {"kraken": 226.62}
    assert broker.live_calls == 0
    assert capital_authority.feed_calls == 0


def test_activation_snapshot_uses_cached_balance_without_private_io(monkeypatch):
    broker = _Broker(cached=226.62)
    capital_authority = _CapitalAuthority()
    _install_cached_modules(monkeypatch, broker, capital_authority)

    accepted, meta = activation._broker_manager_snapshot()

    assert accepted is True
    assert meta["source"] == "broker_manager_cached"
    assert meta["real_capital"] == 226.62
    assert broker.live_calls == 0
    assert capital_authority.feed_calls == 0


def test_recovery_monitors_fail_closed_without_published_balance(monkeypatch):
    broker = _Broker(cached=0.0)
    capital_authority = _CapitalAuthority(balance=0.0)
    _install_cached_modules(monkeypatch, broker, capital_authority)

    payload = convergence._broker_manager_capital_payload()
    accepted, meta = activation._broker_manager_snapshot()

    assert payload["connected_count"] == 0
    assert payload["total_balance"] == 0.0
    assert accepted is False
    assert meta["reason"] == "no_connected_cached_balances"
    assert broker.live_calls == 0
    assert capital_authority.feed_calls == 0


def test_kraken_private_equity_refresh_is_ttl_coalesced(monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_PRIVATE_EQUITY_MIN_REFRESH_S", "60")

    class KrakenBrokerForTest:
        def __init__(self):
            self.calls = 0

        def get_account_balance(self):
            self.calls += 1
            return {"total_funds": 226.62, "source": "private"}

    assert freshness._patch_class(KrakenBrokerForTest) is True
    broker = KrakenBrokerForTest()

    first = broker.get_account_balance()
    second = broker.get_account_balance()

    assert broker.calls == 1
    assert first["total_funds"] == 226.62
    assert second["total_funds"] == 226.62
    assert second["equity_cached_within_ttl"] is True


def test_live_total_selector_logs_once_per_interval(monkeypatch, caplog):
    class CapitalAuthorityForTest:
        def __init__(self):
            self._last_typed_snapshot = SimpleNamespace(real_capital=155.21)
            self._broker_balances = {"kraken": 226.62}
            self._last_updated_total = 155.21

        def get_real_capital(self):
            return 226.62

    module = ModuleType("capital_authority_for_storm_guard_test")
    module.CapitalAuthority = CapitalAuthorityForTest
    monkeypatch.setattr(live_total, "_APPLIED", False)
    assert live_total._patch_module(module) is True

    authority = CapitalAuthorityForTest()
    with caplog.at_level(logging.WARNING, logger=live_total.logger.name):
        assert authority.total_capital == 226.62
        assert authority.total_capital == 226.62

    selected = [
        record for record in caplog.records
        if "CAPITAL_AUTHORITY_LIVE_TOTAL_SELECTED" in record.getMessage()
    ]
    assert len(selected) == 1
