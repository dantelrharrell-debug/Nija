import builtins
import json
from types import SimpleNamespace


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    calls = []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data, "headers": headers or {}, "timeout": timeout})
        if url.endswith("/api/v5/account/balance"):
            return _FakeResponse({"code": "0", "data": [{"totalEq": "123.45", "details": [{"ccy": "USDT", "availBal": "100"}]}]})
        if url.endswith("/api/v5/trade/order"):
            return _FakeResponse({"code": "0", "data": [{"ordId": "okx-order-1"}]})
        return _FakeResponse({"code": "0", "data": []})


class _FakeRequests:
    def Session(self):
        return _FakeSession()


def test_okx_broker_connect_uses_rest_without_sdk_import(monkeypatch):
    import bot.broker_manager as broker_manager
    from bot.broker_manager import AccountType, OKXBroker

    real_import = builtins.__import__

    def guard_import(name, *args, **kwargs):
        if name == "okx" or name.startswith("okx."):
            raise AssertionError("OKX SDK must not be imported; NIJA uses direct REST")
        return real_import(name, *args, **kwargs)

    _FakeSession.calls = []
    monkeypatch.setattr(builtins, "__import__", guard_import)
    monkeypatch.setattr(broker_manager, "_requests_lib", _FakeRequests())
    monkeypatch.setattr(broker_manager, "_REQUESTS_AVAILABLE", True)
    monkeypatch.setenv("OKX_USER_READ_ONLY_CONTAINER_API_KEY", "key-123456789")
    monkeypatch.setenv("OKX_USER_READ_ONLY_CONTAINER_API_SECRET", "secret-123456789")
    monkeypatch.setenv("OKX_USER_READ_ONLY_CONTAINER_PASSPHRASE", "real-okx-passphrase-123")

    broker = OKXBroker(account_type=AccountType.USER, user_id="read_only_container")

    assert broker.connect() is True
    assert broker.connected is True
    assert broker.account_api is broker.trade_api is broker.market_api
    assert _FakeSession.calls[0]["url"].endswith("/api/v5/account/balance")
    assert "OK-ACCESS-SIGN" in _FakeSession.calls[0]["headers"]


def test_okx_broker_market_order_uses_rest_order_endpoint(monkeypatch):
    import bot.broker_manager as broker_manager
    from bot.broker_manager import AccountType, OKXBroker

    _FakeSession.calls = []
    monkeypatch.setattr(broker_manager, "_requests_lib", _FakeRequests())
    monkeypatch.setattr(broker_manager, "_REQUESTS_AVAILABLE", True)
    monkeypatch.setenv("OKX_USER_READ_ONLY_CONTAINER_API_KEY", "key-123456789")
    monkeypatch.setenv("OKX_USER_READ_ONLY_CONTAINER_API_SECRET", "secret-123456789")
    monkeypatch.setenv("OKX_USER_READ_ONLY_CONTAINER_PASSPHRASE", "real-okx-passphrase-123")
    monkeypatch.setattr(broker_manager, "_reject_if_unauthorized_order_submit", lambda *args, **kwargs: None)
    monkeypatch.setattr(broker_manager, "_check_broker_isolation", lambda *args, **kwargs: None)

    broker = OKXBroker(account_type=AccountType.USER, user_id="read_only_container")
    assert broker.connect() is True

    result = broker.place_market_order("BTC-USD", "buy", 5.0)

    assert result["status"] == "filled"
    assert result["order_id"] == "okx-order-1"
    order_call = _FakeSession.calls[-1]
    assert order_call["url"].endswith("/api/v5/trade/order")
    body = json.loads(order_call["data"])
    assert body["instId"] == "BTC-USDT"
    assert body["tdMode"] == "cash"
    assert body["ordType"] == "market"
    assert body["tgtCcy"] == "quote_ccy"


def test_startup_validation_counts_okx_direct_rest_credentials(monkeypatch):
    from bot.startup_validation import validate_exchange_configuration

    monkeypatch.setenv("OKX_API_KEY", "real-looking-okx-key-123456")
    monkeypatch.setenv("OKX_API_SECRET", "real-looking-okx-secret-123456")
    monkeypatch.setenv("OKX_PASSPHRASE", "real-okx-passphrase-123")
    monkeypatch.delenv("NIJA_DISABLE_OKX", raising=False)
    monkeypatch.delenv("KRAKEN_PLATFORM_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_PLATFORM_API_SECRET", raising=False)
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    monkeypatch.delenv("COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    monkeypatch.delenv("COINBASE_PEM_CONTENT", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    result = validate_exchange_configuration()
    info = "\n".join(result.info)

    assert "OKX credentials configured and viable for direct REST trading" in info
    assert "Viable brokers: 1" in info
