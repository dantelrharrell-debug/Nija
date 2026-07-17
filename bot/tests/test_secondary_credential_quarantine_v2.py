from __future__ import annotations

import importlib
import os
from types import ModuleType


quarantine = importlib.import_module("bot.secondary_credential_quarantine_patch")


def test_fatal_okx_code_sets_process_global_quarantine(monkeypatch):
    for key in (
        "NIJA_OKX_CREDENTIALS_QUARANTINED",
        "NIJA_OKX_CREDENTIAL_QUARANTINE_CODE",
        "NIJA_OKX_CONNECTED",
        "NIJA_OKX_TRADING_READY",
        "NIJA_OKX_BALANCE_OBSERVED",
        "NIJA_OKX_ENTRY_ISOLATED",
        "OKX_DISABLE_ENDPOINT_FALLBACK",
        "NIJA_OKX_RECONNECT_DISABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(quarantine, "_LOGGED", False)

    quarantine._publish_quarantine("50111", "/api/v5/account/balance")

    assert quarantine._is_quarantined() is True
    assert os.environ["NIJA_OKX_CONNECTED"] == "0"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "0"
    assert os.environ["NIJA_OKX_ENTRY_ISOLATED"] == "1"
    assert os.environ["OKX_DISABLE_ENDPOINT_FALLBACK"] == "true"
    assert os.environ["NIJA_OKX_RECONNECT_DISABLED"] == "1"


def test_new_okx_broker_instance_does_not_retry_after_global_quarantine(monkeypatch):
    module = ModuleType("bot.broker_manager")
    calls: list[str] = []

    class OKXBroker:
        connected = True
        _is_available = True

        def connect(self):
            calls.append("connect")
            return True

    module.OKXBroker = OKXBroker
    monkeypatch.setenv("NIJA_OKX_CREDENTIALS_QUARANTINED", "1")
    monkeypatch.setenv("NIJA_OKX_CREDENTIAL_QUARANTINE_CODE", "50111")

    assert quarantine._patch_broker(module) is True
    broker = OKXBroker()
    assert broker.connect() is False
    assert calls == []
    assert broker.connected is False
    assert broker._is_available is False


def test_private_okx_request_is_short_circuited_after_global_quarantine(monkeypatch):
    module = ModuleType("bot.broker_manager")
    calls: list[str] = []

    class _OKXRestClient:
        def _request(self, method, path, *args, **kwargs):
            calls.append(path)
            return {"code": "0", "data": []}

    module._OKXRestClient = _OKXRestClient
    monkeypatch.setenv("NIJA_OKX_CREDENTIALS_QUARANTINED", "1")
    monkeypatch.setenv("NIJA_OKX_CREDENTIAL_QUARANTINE_CODE", "50111")

    assert quarantine._patch_rest(module) is True
    result = _OKXRestClient()._request("GET", "/api/v5/account/balance", private=True)
    assert result["quarantined"] is True
    assert result["code"] == "50111"
    assert calls == []
