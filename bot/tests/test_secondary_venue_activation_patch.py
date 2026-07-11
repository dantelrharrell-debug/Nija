from __future__ import annotations

from types import SimpleNamespace

import secondary_venue_activation_patch as patch


class _BrokerType:
    COINBASE = "coinbase"
    OKX = "okx"


class _BrokerModule:
    BrokerType = _BrokerType


class _Broker:
    def __init__(self, *, connected: bool = False, connect_result: bool = True):
        self.connected = connected
        self.connect_result = connect_result
        self._auth_failed = False
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self.connect_result:
            self.connected = True
        return self.connect_result

    def get_available_markets(self):
        return ["BTC-USD", "ETH-USD"]


class _Manager:
    def __init__(self, venue_name: str, broker: _Broker):
        self._platform_brokers = {venue_name: broker}
        self.marked = []
        self.refreshes = []

    def _mark_platform_connected(self, venue):
        self.marked.append(venue)

    def refresh_registry(self):
        return None

    def refresh_capital_authority(self, trigger="manual"):
        self.refreshes.append(trigger)
        return {"ready": 1.0}


def _reset(monkeypatch):
    patch._LAST_STATE.clear()
    patch._SECRET_FP.clear()
    for name in (
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
        "COINBASE_PLATFORM_API_KEY",
        "COINBASE_PLATFORM_API_SECRET",
        "OKX_API_KEY",
        "OKX_API_SECRET",
        "OKX_PASSPHRASE",
        "NIJA_DISABLE_COINBASE",
        "NIJA_DISABLE_OKX",
        "ENABLE_COINBASE",
        "ENABLE_COINBASE_TRADING",
        "COINBASE_LIVE_TRADING_ENABLED",
        "ENABLE_OKX_TRADING",
        "OKX_LIVE_TRADING_ENABLED",
        "NIJA_OKX_EXECUTION_ENABLED",
        "NIJA_OKX_LIVE_TRADING_ENABLED",
        "COINBASE_VENUE_THRESHOLD_USD",
        "OKX_MIN_ORDER_USD",
    ):
        monkeypatch.delenv(name, raising=False)


def _install_spendable_resolver(monkeypatch, value: float):
    real_import = patch.importlib.import_module

    def _fake_import(name: str):
        if name == "bot.spendable_quote_routing_patch":
            return SimpleNamespace(
                _spendable_usd=lambda broker, venue: (value, value, "test")
            )
        return real_import(name)

    monkeypatch.setattr(patch.importlib, "import_module", _fake_import)


def test_coinbase_credential_aliases_are_promoted(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("COINBASE_PLATFORM_API_KEY", "key")
    monkeypatch.setenv("COINBASE_PLATFORM_API_SECRET", "secret")

    ok, missing, _fingerprint = patch._credentials(patch.VENUES[0])

    assert ok is True
    assert missing == []
    assert patch.os.environ["COINBASE_API_KEY"] == "key"
    assert patch.os.environ["COINBASE_API_SECRET"] == "secret"


def test_okx_missing_credentials_remains_fail_closed(monkeypatch):
    _reset(monkeypatch)

    state = patch.activate_once(patch.VENUES[1], _BrokerModule, object())

    assert state == "missing_credentials"
    assert patch.os.environ["NIJA_OKX_ACTIVATION_STATE"] == "missing_credentials"


def test_connected_coinbase_becomes_ready_with_own_spendable_cash(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("COINBASE_API_KEY", "key")
    monkeypatch.setenv("COINBASE_API_SECRET", "secret")
    _install_spendable_resolver(monkeypatch, 20.0)
    broker = _Broker(connected=False, connect_result=True)
    manager = _Manager("coinbase", broker)

    state = patch.activate_once(patch.VENUES[0], _BrokerModule, manager)

    assert state == "ready"
    assert broker.connect_calls == 1
    assert patch.os.environ["NIJA_COINBASE_CONNECTED"] == "1"
    assert patch.os.environ["NIJA_COINBASE_TRADING_READY"] == "1"
    assert manager.refreshes == ["secondary_venue_activation:coinbase"]


def test_connected_okx_without_minimum_cash_is_not_admitted(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_API_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSPHRASE", "passphrase")
    _install_spendable_resolver(monkeypatch, 4.0)
    broker = _Broker(connected=True)
    manager = _Manager("okx", broker)

    state = patch.activate_once(patch.VENUES[1], _BrokerModule, manager)

    assert state == "connected_unfunded"
    assert patch.os.environ["NIJA_OKX_TRADING_READY"] == "0"
    assert manager.refreshes == ["secondary_venue_activation:okx"]


def test_explicit_disable_prevents_connection_attempt(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("COINBASE_API_KEY", "key")
    monkeypatch.setenv("COINBASE_API_SECRET", "secret")
    monkeypatch.setenv("NIJA_DISABLE_COINBASE", "true")
    broker = _Broker(connected=False)
    manager = _Manager("coinbase", broker)

    state = patch.activate_once(patch.VENUES[0], _BrokerModule, manager)

    assert state == "disabled"
    assert broker.connect_calls == 0
