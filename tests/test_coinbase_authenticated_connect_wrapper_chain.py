from __future__ import annotations

import importlib
import sys

import pytest


def _module():
    return importlib.import_module("coinbase_authenticated_connect_recovery_patch")


@pytest.fixture(autouse=True)
def _clear_canonical_brokers():
    module = _module()
    with module._LOCK:
        module._CANONICAL_BROKERS.clear()
    manager = sys.modules.get("bot.broker_manager")
    saved_registry = None
    if manager is not None:
        lock = getattr(manager, "_PLATFORM_BROKER_REGISTRY_LOCK")
        with lock:
            saved_registry = (
                getattr(manager, "GLOBAL_PLATFORM_BROKERS").get("coinbase", False),
                getattr(manager, "_PLATFORM_BROKER_INSTANCES").get("coinbase"),
                getattr(manager, "_PLATFORM_BROKER_CONNECTED").get("coinbase", False),
            )
            getattr(manager, "GLOBAL_PLATFORM_BROKERS")["coinbase"] = False
            getattr(manager, "_PLATFORM_BROKER_INSTANCES").pop("coinbase", None)
            getattr(manager, "_PLATFORM_BROKER_CONNECTED")["coinbase"] = False
    yield
    with module._LOCK:
        module._CANONICAL_BROKERS.clear()
    if manager is not None and saved_registry is not None:
        existed, broker, connected = saved_registry
        lock = getattr(manager, "_PLATFORM_BROKER_REGISTRY_LOCK")
        with lock:
            getattr(manager, "GLOBAL_PLATFORM_BROKERS")["coinbase"] = existed
            if broker is None:
                getattr(manager, "_PLATFORM_BROKER_INSTANCES").pop("coinbase", None)
            else:
                getattr(manager, "_PLATFORM_BROKER_INSTANCES")["coinbase"] = broker
            getattr(manager, "_PLATFORM_BROKER_CONNECTED")["coinbase"] = connected


def test_wrapper_chain_detects_nested_recovery_marker():
    module = _module()

    def original(self):
        return True

    def recovery(self):
        return original(self)

    setattr(recovery, module._PATCH_ATTR, True)
    recovery.__wrapped__ = original

    def outer(self):
        return recovery(self)

    outer.__wrapped__ = recovery

    assert module._wrapper_chain_has_patch(outer) is True


def test_patch_class_does_not_duplicate_nested_recovery_wrapper():
    module = _module()

    def original(self):
        return True

    def recovery(self):
        return original(self)

    setattr(recovery, module._PATCH_ATTR, True)
    recovery.__wrapped__ = original

    def outer(self):
        return recovery(self)

    outer.__wrapped__ = recovery

    class CoinbaseBroker:
        connect = outer

    before = CoinbaseBroker.connect
    assert module._patch_class(CoinbaseBroker) is True
    assert CoinbaseBroker.connect is before


def test_wrapper_chain_cycle_is_safe():
    module = _module()

    def outer(self):
        return True

    outer.__wrapped__ = outer
    assert module._wrapper_chain_has_patch(outer) is False


def test_authenticated_probe_deduplicates_clients_by_identity():
    module = _module()

    class Client:
        def __eq__(self, other):
            raise AssertionError("client equality must never be evaluated")

        def get_accounts(self):
            return {"accounts": []}

    client = Client()
    broker = type(
        "CoinbaseBroker",
        (),
        {"client": client, "api_client": client},
    )()

    authenticated, source = module._authenticated_probe(broker)

    assert authenticated is True
    assert source == "Client.get_accounts"


def test_recursive_connect_reentry_fails_closed(monkeypatch):
    module = _module()

    class CoinbaseBroker:
        def __init__(self):
            self.client = None
            self.connected = False
            self._is_available = True
            self._auth_failed = False

        def connect(self):
            return self.connect()

    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key")
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\nTEST\n-----END EC PRIVATE KEY-----",
    )
    monkeypatch.delenv("NIJA_COINBASE_CREDENTIALS_QUARANTINED", raising=False)
    monkeypatch.setattr(module, "_configured_pairs", lambda: [])

    assert module._patch_class(CoinbaseBroker) is True
    broker = CoinbaseBroker()

    assert broker.connect() is False
    assert broker.connected is False
    assert broker._is_available is False
    assert module.os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert module.os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "connect_recursion_blocked"


def test_disconnected_broker_rebuilds_client_and_clears_transient_auth_latch(monkeypatch):
    module = _module()

    class Client:
        def get_accounts(self):
            return {"accounts": []}

    class CoinbaseBroker:
        def __init__(self):
            self.client = None
            self.connected = False
            self._auth_failed = True
            self._is_available = False
            self._balance_fetch_errors = 3

        def connect(self):
            assert self._auth_failed is False
            assert self.client is None
            self.client = Client()
            self.connected = True
            return True

    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key")
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\nTEST\n-----END EC PRIVATE KEY-----",
    )
    monkeypatch.delenv("NIJA_COINBASE_CREDENTIALS_QUARANTINED", raising=False)
    monkeypatch.delenv("NIJA_COINBASE_RECONNECT_DISABLED", raising=False)
    monkeypatch.setattr(module, "_measure_spendable", lambda broker: 200.25)

    assert module._patch_class(CoinbaseBroker) is True
    broker = CoinbaseBroker()

    assert broker.connect() is True
    assert broker.connected is True
    assert broker.client is not None
    assert broker._auth_failed is False
    assert broker._is_available is True
    assert broker._balance_fetch_errors == 0
    assert module.os.environ["NIJA_COINBASE_CONNECTED"] == "1"
    assert module.os.environ["NIJA_COINBASE_TRADING_READY"] == "1"
    assert module.os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "ready"


def test_connected_broker_with_missing_client_triggers_rebuild(monkeypatch):
    """connected=True but client=None must force a full rebuild before declaring recovery."""
    module = _module()

    class Client:
        def get_accounts(self):
            return {"accounts": []}

    rebuilt = []

    class CoinbaseBroker:
        def __init__(self):
            # Simulate the inconsistent state: connected flag set but client lost.
            self.client = None
            self.connected = True
            self._auth_failed = False
            self._is_available = True
            self._accounts_cache = None
            self._accounts_cache_time = None
            self._balance_cache = {"usd": 500.0}  # stale cached balance
            self._balance_cache_time = None

        def connect(self):
            # When _apply_pair resets state, connected is False and client is None.
            assert self.connected is False, "state must be reset before rebuilding"
            assert self.client is None, "client must be cleared before rebuild"
            self.client = Client()
            self.connected = True
            rebuilt.append(True)
            return True

    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key")
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\nTEST\n-----END EC PRIVATE KEY-----",
    )
    monkeypatch.delenv("NIJA_COINBASE_CREDENTIALS_QUARANTINED", raising=False)
    monkeypatch.delenv("NIJA_COINBASE_RECONNECT_DISABLED", raising=False)
    monkeypatch.setattr(module, "_measure_spendable", lambda broker: 500.0)

    assert module._patch_class(CoinbaseBroker) is True
    broker = CoinbaseBroker()

    assert broker.connect() is True
    assert rebuilt == [True], "original connect() must have been called to rebuild the client"
    assert broker.client is not None
    assert broker.connected is True
    assert module.os.environ["NIJA_COINBASE_CONNECTED"] == "1"
    assert module.os.environ["NIJA_COINBASE_TRADING_READY"] == "1"


def test_transient_connect_failure_stays_retryable(monkeypatch):
    module = _module()

    class CoinbaseBroker:
        def __init__(self):
            self.client = None
            self.connected = False
            self._auth_failed = False
            self._is_available = True

        def connect(self):
            return False

    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key")
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\nTEST\n-----END EC PRIVATE KEY-----",
    )
    monkeypatch.delenv("NIJA_COINBASE_CREDENTIALS_QUARANTINED", raising=False)
    monkeypatch.delenv("NIJA_COINBASE_RECONNECT_DISABLED", raising=False)
    monkeypatch.setattr(module, "_configured_pairs", lambda: [])

    assert module._patch_class(CoinbaseBroker) is True
    broker = CoinbaseBroker()

    assert broker.connect() is False
    assert broker.connected is False
    assert broker._auth_failed is False
    assert broker._is_available is False
    assert module.os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "reconnect_pending"
    assert module.os.environ.get("NIJA_COINBASE_RECONNECT_DISABLED", "0") != "1"
