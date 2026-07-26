from __future__ import annotations

import os
import weakref
from types import ModuleType

import coinbase_authenticated_connect_recovery_patch as recovery
import runtime_auth_recursion_endpoint_repair_patch as repair


def test_coinbase_balance_fails_closed_when_client_is_missing(monkeypatch):
    class Stability:
        def __init__(self):
            self.reasons = []

        def mark_disconnected(self, reason):
            self.reasons.append(reason)

    class CoinbaseBroker:
        def __init__(self):
            self.client = None
            self.connected = True
            self._is_available = True
            self._auth_failed = False
            self._connection_stability_manager = Stability()

        def _get_account_balance_detailed(self, verbose=False):
            raise AssertionError("uninitialized client must not reach original detailed method")

        def get_account_balance(self, verbose=False):
            raise AssertionError("uninitialized client must not reach original float method")

        def get_balance(self):
            raise AssertionError("uninitialized client must not reach original float method")

    module = ModuleType("bot.broker_manager")
    module.CoinbaseBroker = CoinbaseBroker

    assert repair._patch_coinbase_class(module) is True
    broker = CoinbaseBroker()
    payload = broker._get_account_balance_detailed()

    assert payload["total_funds"] == 0.0
    assert payload["trading_balance"] == 0.0
    assert payload["connected"] is False
    assert broker.get_account_balance() == 0.0
    assert broker.get_balance() == 0.0
    assert broker.connected is False
    assert broker._is_available is False
    assert broker._auth_failed is False
    assert broker._connection_stability_manager.reasons == [
        "client_uninitialized",
        "client_uninitialized",
        "client_uninitialized",
    ]
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_FUNDING_STATUS"] == "client_uninitialized"
    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "reconnect_pending"


def test_coinbase_stale_instance_adopts_same_account_canonical_client(monkeypatch):
    class AccountType:
        value = "platform"

    class Client:
        def get_accounts(self):
            return {"accounts": []}

    class Stability:
        def __init__(self):
            self.reasons = []

        def mark_disconnected(self, reason):
            self.reasons.append(reason)

    class CoinbaseBroker:
        account_type = AccountType()
        user_id = None

        def __init__(self, client=None):
            self.client = client
            self.connected = client is not None
            self._is_available = client is not None
            self._auth_failed = False
            self._connection_stability_manager = Stability()

        def _get_account_balance_detailed(self, verbose=False):
            assert self.client is canonical.client
            return {"total_funds": 142.76, "trading_balance": 100.11}

        def get_account_balance(self, verbose=False):
            return self._get_account_balance_detailed()["trading_balance"]

        def get_balance(self):
            return self.get_account_balance()

    canonical = CoinbaseBroker(Client())
    stale = CoinbaseBroker()
    with recovery._LOCK:
        recovery._CANONICAL_BROKERS["platform"] = weakref.ref(canonical)
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")

    module = ModuleType("bot.broker_manager")
    module.CoinbaseBroker = CoinbaseBroker
    assert repair._patch_coinbase_class(module) is True

    payload = stale._get_account_balance_detailed()

    assert payload["total_funds"] == 142.76
    assert stale.client is canonical.client
    assert stale.connected is True
    assert stale._connection_stability_manager.reasons == []
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "1"


def test_coinbase_canonical_client_is_never_shared_between_users():
    class AccountType:
        value = "user"

    class CoinbaseBroker:
        account_type = AccountType()

        def __init__(self, user_id, client=None):
            self.user_id = user_id
            self.client = client
            self.connected = client is not None
            self._auth_failed = False

    tania = CoinbaseBroker("tania", object())
    daivon = CoinbaseBroker("daivon")
    with recovery._LOCK:
        recovery._CANONICAL_BROKERS["user:tania"] = weakref.ref(tania)

    assert recovery.adopt_canonical_client(daivon) is False
    assert daivon.client is None


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
