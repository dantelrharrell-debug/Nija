from __future__ import annotations

import os
import sys
import threading
import time
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


def test_coinbase_recursive_connect_is_blocked(monkeypatch):
    class Stability:
        def __init__(self):
            self.reasons = []

        def mark_disconnected(self, reason):
            self.reasons.append(reason)

    class CoinbaseBroker:
        def __init__(self):
            self.connected = True
            self._is_available = True
            self._auth_failed = False
            self._connection_stability_manager = Stability()

        def connect(self):
            return self.connect()

    module = ModuleType("bot.broker_manager")
    module.CoinbaseBroker = CoinbaseBroker

    assert repair._patch_coinbase_class(module) is True
    broker = CoinbaseBroker()

    assert broker.connect() is False
    assert broker.connected is False
    assert broker._is_available is False
    assert broker._auth_failed is False
    assert broker._connection_stability_manager.reasons == ["connect_recursion_blocked"]
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_FUNDING_STATUS"] == "connect_recursion_blocked"
    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "reconnect_pending"


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


def test_okx_failed_initialization_releases_guard_and_allows_retry(monkeypatch):
    class OKXBroker:
        def __init__(self):
            self.connected = False
            self._auth_failed = False
            self._connect_lock = threading.RLock()
            self.calls = 0

        def connect(self):
            self.calls += 1
            if self.calls == 1:
                self._auth_failed = True
                raise RuntimeError("401 invalid OKX signature")
            self.connected = True
            return True

    module = ModuleType("bot.broker_manager")
    module.OKXBroker = OKXBroker
    assert repair._patch_okx_class(module) is True
    broker = OKXBroker()

    assert broker.connect() is False
    assert broker._auth_failed is False
    assert broker.connected is False
    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "reconnect_pending"
    assert broker.connect() is True
    assert broker.calls == 2


def test_okx_live_attempt_blocks_concurrent_connect_without_mutating_owner(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class OKXBroker:
        def __init__(self):
            self.connected = False

        def connect(self):
            entered.set()
            release.wait(2)
            self.connected = True
            return True

    module = ModuleType("bot.broker_manager")
    module.OKXBroker = OKXBroker
    assert repair._patch_okx_class(module) is True
    broker = OKXBroker()
    result = []
    worker = threading.Thread(target=lambda: result.append(broker.connect()))
    worker.start()
    assert entered.wait(1)

    assert broker.connect() is False
    assert broker.connected is False
    release.set()
    worker.join(2)
    assert result == [True]
    assert broker.connected is True


def test_okx_stale_attempt_is_reclaimed(monkeypatch):
    monkeypatch.setenv("NIJA_OKX_CONNECT_STALE_TIMEOUT_S", "1")

    class OKXBroker:
        def __init__(self):
            self.connected = False
            self.calls = 0

        def connect(self):
            self.calls += 1
            self.connected = True
            return True

    module = ModuleType("bot.broker_manager")
    module.OKXBroker = OKXBroker
    assert repair._patch_okx_class(module) is True
    broker = OKXBroker()
    token, blocked = repair._begin_okx_connect_attempt(broker)
    assert token is not None and blocked is None
    broker._nija_okx_connect_attempt["started_at"] = time.monotonic() - 2

    assert broker.connect() is True
    assert broker.calls == 1


def test_okx_reentry_log_preserves_original_exception(monkeypatch, caplog):
    class OKXBroker:
        def __init__(self):
            self.connected = False

        def connect(self):
            try:
                raise ValueError("first authentication failure")
            except ValueError:
                return self.connect()

    module = ModuleType("bot.broker_manager")
    module.OKXBroker = OKXBroker
    assert repair._patch_okx_class(module) is True
    broker = OKXBroker()

    with caplog.at_level("ERROR"):
        assert broker.connect() is False
    assert "original_error=ValueError: first authentication failure" in caplog.text


def test_runtime_convergence_repair_is_idempotent(monkeypatch):
    module = ModuleType("runtime_convergence_hardening_patch")

    def unsafe_patch_auth_surface(target):
        return True

    module._patch_auth_surface = unsafe_patch_auth_surface
    monkeypatch.setitem(sys.modules, "runtime_convergence_hardening_patch", module)

    assert repair._disable_recursive_convergence_hook() is True
    first = module._patch_auth_surface
    assert getattr(first, "_nija_runtime_convergence_recursion_safe_v2") is True

    assert repair._disable_recursive_convergence_hook() is False
    assert module._patch_auth_surface is first
