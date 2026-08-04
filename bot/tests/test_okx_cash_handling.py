from __future__ import annotations

import logging
import importlib

from bot.broker_manager import OKXBroker, _OKXRestClient, _okx_spendable_cash


class _AccountAPI:
    def __init__(self, details):
        self._details = details

    def get_balance(self):
        return {"code": "0", "data": [{"details": self._details}]}


def _broker(details):
    broker = OKXBroker.__new__(OKXBroker)
    broker.account_api = _AccountAPI(details)
    broker.market_api = None
    broker._last_known_balance = None
    broker._balance_fetch_errors = 0
    broker._is_available = True
    broker.account_identifier = "PLATFORM"
    return broker


def test_okx_spendable_cash_sums_usd_usdt_and_usdc():
    details = [
        {"ccy": "USD", "availBal": "144.96", "cashBal": "144.96"},
        {"ccy": "USDT", "availBal": "2.50"},
        {"ccy": "USDC", "availBal": "", "cashBal": "1.25"},
        {"ccy": "ETH", "availBal": "3"},
    ]

    assert _okx_spendable_cash(details) == {
        "USD": 144.96,
        "USDT": 2.5,
        "USDC": 1.25,
    }


def test_okx_account_balance_counts_all_quote_cash(monkeypatch):
    broker = _broker(
        [
            {"ccy": "USD", "availBal": "144.96"},
            {"ccy": "USDT", "availBal": "2.50"},
            {"ccy": "USDC", "availBal": "1.25"},
        ]
    )
    monkeypatch.setattr(broker, "get_positions", lambda: [])

    assert broker.get_account_balance(verbose=False) == 148.71
    assert broker._last_known_balance == 148.71


def test_okx_positions_exclude_quote_cash_and_never_request_usd_usdt(monkeypatch):
    details = [
        {"ccy": "USD", "availBal": "144.96"},
        {"ccy": "USDT", "availBal": "2.50"},
        {"ccy": "USDC", "availBal": "1.25"},
        {"ccy": "ETH", "availBal": "0.5"},
    ]
    broker = _broker(details)

    class _MarketAPI:
        def get_tickers(self, instType):
            assert instType == "SPOT"
            return {
                "code": "0",
                "data": [{"instId": "ETH-USDT", "last": "1915.38"}],
            }

    broker.market_api = _MarketAPI()
    monkeypatch.setattr(
        broker,
        "get_current_price",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError(f"unexpected individual ticker request: {symbol}")
        ),
    )

    positions = broker.get_positions()

    assert [position["symbol"] for position in positions] == ["ETH-USD"]
    assert positions[0]["size_usd"] == 957.69


class _Response:
    def __init__(self, body, *, status_code=200, text=None):
        self._body = body
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.text = text if text is not None else repr(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, response):
        self.response = response

    def request(self, *args, **kwargs):
        return self.response


def _rest_client(response):
    client = _OKXRestClient.__new__(_OKXRestClient)
    client.api_key = "api-key"
    client.api_secret = "api-secret"
    client.passphrase = "passphrase"
    client.simulated = False
    client.timeout = 10.0
    client.BASE_URL = "https://us.okx.com"
    client.session = _Session(response)
    return client


def test_okx_success_response_does_not_emit_raw_payload_at_warning(caplog):
    raw_text = '{"code":"0","data":[{"private":"sensitive-balance"}]}'
    client = _rest_client(
        _Response(
            {"code": "0", "msg": "", "data": [{"private": "sensitive-balance"}]},
            text=raw_text,
        )
    )

    with caplog.at_level(logging.DEBUG, logger="nija.broker"):
        result = client.get_balance()

    assert result["code"] == "0"
    warning_or_higher = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    assert warning_or_higher == []
    assert all(raw_text not in record.getMessage() for record in caplog.records)
    assert all("sensitive-balance" not in record.getMessage() for record in caplog.records)
    assert any(
        "OKX_RESPONSE_DIAG" in record.getMessage()
        and "data_items=1" in record.getMessage()
        for record in caplog.records
    )


def test_okx_application_error_is_bounded_and_omits_raw_payload(caplog):
    raw_text = '{"code":"51001","msg":"Instrument does not exist","data":[]}'
    client = _rest_client(
        _Response(
            {"code": "51001", "msg": "Instrument does not exist", "data": []},
            text=raw_text,
        )
    )

    with caplog.at_level(logging.DEBUG, logger="nija.broker"):
        result = client.get_ticker("BAD-USDT")

    assert result["code"] == "51001"
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        ("OKX_API_ERROR" in message or "OKX_REQUEST_FAILED" in message)
        and "okx_code=51001" in message
        and "Instrument does not exist" in message
        for message in messages
    )
    assert all(raw_text not in message for message in messages)
    assert all("key_sample" not in message for message in messages)


def test_exchange_normalizer_removes_generated_usdtt_suffix():
    normalizer = importlib.import_module("bot.exchange_normalizer")

    assert normalizer._clean_symbol("BTC-USDTT") == "BTC-USDT"
    assert normalizer._clean_symbol("BTCUSDTT") == "BTCUSDT"


def test_okx_get_candles_skips_unlisted_instrument_before_request(monkeypatch):
    patch = importlib.import_module("bot.okx_runtime_patch")

    class MarketAPI:
        def __init__(self):
            self.calls = []

        def _request(self, method, path, params=None):
            self.calls.append((method, path, params))
            if path == "/api/v5/public/instruments":
                return {"code": "0", "data": [{"instId": "ETH-USDT"}]}
            raise AssertionError(f"unexpected request path: {path}")

        def get_candles(self, **kwargs):
            self.calls.append(("GET", "/api/v5/market/candles", kwargs))
            raise AssertionError("candle request should not be sent for unlisted symbol")

    broker = OKXBroker.__new__(OKXBroker)
    broker.market_api = MarketAPI()
    broker.account_api = None
    broker.broker_type = type("BrokerType", (), {"value": "okx"})()

    patch._PRODUCT_CACHE["loaded_at"] = 0.0
    patch._PRODUCT_CACHE["symbols"] = set()
    patch._INVALID_OKX_INST_IDS.clear()

    result = patch._direct_get_candles(broker, "BTC-USD", timeframe="1m", limit=5)

    assert result is None
    assert ("GET", "/api/v5/public/instruments", {"instType": "SPOT"}) in broker.market_api.calls
    assert all(call[1] != "/api/v5/market/candles" for call in broker.market_api.calls)
    assert "BTC-USDT" in patch._INVALID_OKX_INST_IDS
