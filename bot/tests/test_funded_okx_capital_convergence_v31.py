from __future__ import annotations

import os
from types import SimpleNamespace

import bot.activation_pending_commit_monitor_patch as activation_monitor
import bot.coinbase_balance_auth_convergence_patch as coinbase_balance
import bot.okx_funding_wallet_readiness_patch as okx_wallet
import coinbase_authenticated_connect_recovery_patch as coinbase_connect
import secondary_venue_activation_patch as secondary_activation
import three_venue_execution_readiness as three_venue


class _OKXAccountAPI:
    def get_balance(self):
        return {
            "code": "0",
            "data": [
                {
                    "totalEq": "144.96328582635033",
                    "details": [
                        {
                            "ccy": "USD",
                            "availBal": "144.96287318736722",
                            "cashBal": "144.96287318736722",
                        },
                        {
                            "ccy": "ETH",
                            "availBal": "0.0000002208633426",
                            "eqUsd": "0.0004126389829796",
                        },
                    ],
                }
            ],
        }


def _clear_coinbase_quarantine(monkeypatch) -> None:
    for name in (
        "NIJA_COINBASE_CREDENTIALS_QUARANTINED",
        "NIJA_COINBASE_RECONNECT_DISABLED",
        "NIJA_COINBASE_QUARANTINED_CREDENTIAL_FINGERPRINT",
        "NIJA_COINBASE_CONNECTED",
        "NIJA_COINBASE_BALANCE_OBSERVED",
        "NIJA_COINBASE_SPENDABLE_QUOTE",
        "NIJA_COINBASE_TRADING_READY",
        "NIJA_COINBASE_ACTIVATED",
        "NIJA_COINBASE_ACTIVATION_STATE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_okx_private_wallet_value_is_monotonic_through_legacy_wrapper(monkeypatch):
    monkeypatch.setenv("OKX_MIN_ORDER_USD", "10")

    class OKXBroker:
        def __init__(self):
            self.account_api = _OKXAccountAPI()
            self.connected = True

        def get_account_balance(self):
            return 0.0

    assert okx_wallet._patch_class(OKXBroker) is True
    broker = OKXBroker()

    assert broker.get_account_balance() == 144.96328582635033
    assert broker._last_known_balance == 144.96328582635033
    assert broker._last_confirmed_balance == 144.96328582635033
    assert os.environ["NIJA_OKX_CONNECTED"] == "1"
    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "ready"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "1"


def test_secondary_activation_prefers_authenticated_okx_over_zero_router(
    monkeypatch,
):
    secondary_activation._LAST_STATE.clear()
    for name, value in {
        "OKX_API_KEY": "key",
        "OKX_API_SECRET": "secret",
        "OKX_PASSPHRASE": "passphrase",
        "OKX_MIN_ORDER_USD": "10",
        "NIJA_OKX_BALANCE_OBSERVED": "1",
        "NIJA_OKX_FUNDING_STATUS": "funded",
        "NIJA_OKX_TRADING_SPENDABLE_QUOTE": "144.96287319",
        "NIJA_OKX_SPENDABLE_QUOTE": "144.96287319",
    }.items():
        monkeypatch.setenv(name, value)

    real_import = secondary_activation.importlib.import_module

    def fake_import(name: str):
        if name == "bot.spendable_quote_routing_patch":
            return SimpleNamespace(
                _spendable_usd=lambda broker, venue: (0.0, 0.0, "stale_router")
            )
        return real_import(name)

    monkeypatch.setattr(secondary_activation.importlib, "import_module", fake_import)

    class Broker:
        connected = True
        _okx_trading_spendable_quote = 144.96287319

        def get_available_markets(self):
            return ["BTC-USD"]

    broker = Broker()

    class BrokerType:
        OKX = "okx"

    class Manager:
        _platform_brokers = {"okx": broker}

        def _mark_platform_connected(self, venue):
            return None

        def refresh_registry(self):
            return None

        def refresh_capital_authority(self, trigger="manual"):
            return {"trigger": trigger}

    state = secondary_activation.activate_once(
        secondary_activation.VENUES[1],
        SimpleNamespace(BrokerType=BrokerType),
        Manager(),
    )

    assert state == "ready"
    assert os.environ["NIJA_OKX_ACTIVATION_STATE"] == "ready"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "1"
    assert float(os.environ["NIJA_OKX_SPENDABLE_QUOTE"]) == 144.96287319


def test_three_venue_gate_uses_authenticated_okx_cache_without_private_refetch(
    monkeypatch,
):
    for name, value in {
        "OKX_API_KEY": "key",
        "OKX_API_SECRET": "secret",
        "OKX_PASSPHRASE": "passphrase",
        "NIJA_OKX_CONNECTED": "1",
        "NIJA_OKX_BALANCE_OBSERVED": "1",
        "NIJA_OKX_FUNDING_STATUS": "funded",
        "NIJA_OKX_TRADING_SPENDABLE_QUOTE": "144.96287319",
        "NIJA_OKX_SPENDABLE_QUOTE": "144.96287319",
        "NIJA_OKX_ACTIVATION_STATE": "ready",
        "NIJA_OKX_TRADING_READY": "1",
    }.items():
        monkeypatch.setenv(name, value)

    class Broker:
        connected = True
        _okx_trading_spendable_quote = 144.96287319

        def get_account_balance(self):
            raise AssertionError("authenticated cache should avoid another private probe")

        def get_available_markets(self):
            return ["BTC-USD"]

        def place_market_order(self, *args, **kwargs):
            return {"ok": True}

    broker = Broker()

    class BrokerType:
        OKX = "okx"

    manager = SimpleNamespace(
        _platform_brokers={"okx": broker},
        eligible_brokers={broker},
    )
    result = three_venue.evaluate_venue(
        "okx",
        SimpleNamespace(BrokerType=BrokerType),
        manager,
    )

    assert result.ready is True
    assert result.spendable_quote == 144.96287319
    assert result.activation_state == "ready"


def test_activation_monitor_accepts_only_funded_authenticated_okx_cache(
    monkeypatch,
):
    for name, value in {
        "NIJA_OKX_BALANCE_OBSERVED": "1",
        "NIJA_OKX_FUNDING_STATUS": "funded",
        "NIJA_OKX_TRADING_TOTAL_QUOTE": "144.96328583",
        "NIJA_OKX_TRADING_SPENDABLE_QUOTE": "144.96287319",
    }.items():
        monkeypatch.setenv(name, value)

    broker = SimpleNamespace(
        connected=True,
        _okx_trading_total_quote=144.96328582635033,
        _okx_trading_spendable_quote=144.96287318736722,
    )
    amount, source = activation_monitor._cached_broker_balance(
        broker, "okx", None
    )
    assert amount == 144.96328582635033
    assert source == "okx_authenticated_wallet"

    monkeypatch.setenv("NIJA_OKX_FUNDING_STATUS", "under_minimum")
    amount, source = activation_monitor._cached_broker_balance(
        SimpleNamespace(connected=True, _last_known_balance=144.96328582635033),
        "okx",
        None,
    )
    assert amount == 0.0
    assert source == "okx_authenticated_wallet_unavailable"


def test_coinbase_connect_quarantines_confirmed_401_and_stops_retries(
    monkeypatch,
):
    _clear_coinbase_quarantine(monkeypatch)
    monkeypatch.setenv("COINBASE_API_KEY", "key")
    monkeypatch.setenv("COINBASE_API_SECRET", "secret")
    monkeypatch.setattr(coinbase_connect, "_configured_pairs", lambda: [])

    class CoinbaseBroker:
        def __init__(self):
            self.connected = False
            self.connect_calls = 0
            self.account_calls = 0

        def connect(self):
            self.connect_calls += 1
            return False

        def get_accounts(self):
            self.account_calls += 1
            raise RuntimeError("401 Unauthorized")

    assert coinbase_connect._patch_class(CoinbaseBroker) is True
    broker = CoinbaseBroker()

    assert broker.connect() is False
    assert os.environ["NIJA_COINBASE_CREDENTIALS_QUARANTINED"] == "1"
    assert os.environ["NIJA_COINBASE_RECONNECT_DISABLED"] == "1"
    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "quarantined"

    assert broker.connect() is False
    assert broker.connect_calls == 1
    assert broker.account_calls == 1


def test_coinbase_balance_quarantine_returns_fail_closed_zero_without_retries(
    monkeypatch,
):
    _clear_coinbase_quarantine(monkeypatch)
    monkeypatch.setenv("COINBASE_API_KEY", "key")
    monkeypatch.setenv("COINBASE_API_SECRET", "secret")
    monkeypatch.setattr(coinbase_balance, "_normalise", lambda: True)

    class CoinbaseBroker:
        def __init__(self):
            self.connected = True
            self.calls = 0

        def get_account_balance(self):
            self.calls += 1
            raise RuntimeError("401 Client Error: Unauthorized")

    assert coinbase_balance._patch_class(CoinbaseBroker) is True
    broker = CoinbaseBroker()

    assert broker.get_account_balance() == 0.0
    assert os.environ["NIJA_COINBASE_CREDENTIALS_QUARANTINED"] == "1"
    assert os.environ["NIJA_COINBASE_QUARANTINED_CREDENTIAL_FINGERPRINT"]
    assert broker.connected is False

    assert broker.get_account_balance() == 0.0
    assert broker.calls == 1
