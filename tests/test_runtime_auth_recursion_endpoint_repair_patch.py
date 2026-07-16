from __future__ import annotations

import os
from types import ModuleType

import runtime_auth_recursion_endpoint_repair_patch as repair


def test_coinbase_balance_fails_closed_when_client_is_missing(monkeypatch):
    class CoinbaseBroker:
        def __init__(self):
            self.client = None
            self.connected = True

        def _get_account_balance_detailed(self, verbose=False):
            raise AssertionError("uninitialized client must not reach original balance method")

    module = ModuleType("bot.broker_manager")
    module.CoinbaseBroker = CoinbaseBroker

    assert repair._patch_coinbase_class(module) is True
    broker = CoinbaseBroker()
    payload = broker._get_account_balance_detailed()

    assert payload["total_funds"] == 0.0
    assert payload["trading_balance"] == 0.0
    assert payload["connected"] is False
    assert broker.connected is False
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_FUNDING_STATUS"] == "client_uninitialized"


def test_okx_recursive_connect_is_blocked(monkeypatch):
    class OKXBroker:
        def __init__(self):
            self.connected = True

        def connect(self):
            return self.connect()

    module = ModuleType("bot.broker_manager")
    module.OKXBroker = OKXBroker

    assert repair._patch_okx_class(module) is True
    broker = OKXBroker()

    assert broker.connect() is False
    assert broker.connected is False
    assert os.environ["NIJA_OKX_CONNECTED"] == "0"
    assert os.environ["NIJA_OKX_FUNDING_STATUS"] == "connect_recursion_blocked"


def test_okx_endpoint_is_applied_without_recursion(monkeypatch):
    monkeypatch.setenv("OKX_BASE_URL", "https://us.okx.com")

    class OKXBroker:
        def __init__(self):
            self.connected = False
            self.base_url = ""

        def connect(self):
            self.connected = True
            return True

    module = ModuleType("bot.broker_manager")
    module.OKXBroker = OKXBroker

    assert repair._patch_okx_class(module) is True
    broker = OKXBroker()

    assert broker.connect() is True
    assert broker.connected is True
    assert broker.base_url == "https://us.okx.com"
