from __future__ import annotations

import importlib


def _module():
    return importlib.import_module("coinbase_authenticated_connect_recovery_patch")


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
