from __future__ import annotations

import base64
import importlib
import json
import os
import sys
import types


def _module():
    return importlib.import_module("bot.coinbase_funding_readiness_repair_patch")


def test_nested_cdp_json_and_unpadded_base64(monkeypatch):
    module = _module()
    pem = "-----BEGIN EC PRIVATE KEY-----\nQUJDREVGRw==\n-----END EC PRIVATE KEY-----\n"
    encoded = base64.urlsafe_b64encode(pem.encode()).decode().rstrip("=")
    payload = {
        "credentials": {
            "apiKeyName": "organizations/test/apiKeys/key-1",
            "private_key": encoded,
        }
    }
    for name in list(os.environ):
        if name.startswith("COINBASE_") or name.startswith("CDP_API_KEY"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COINBASE_CDP_CREDENTIALS", json.dumps(payload))
    assert module.recover_coinbase_environment() is True
    assert os.environ["COINBASE_API_KEY"] == "organizations/test/apiKeys/key-1"
    assert os.environ["COINBASE_API_SECRET"].startswith("-----BEGIN EC PRIVATE KEY-----")
    assert os.environ["NIJA_COINBASE_CREDENTIALS_NORMALIZED"] == "1"


def test_broker_and_adapter_surfaces_are_patched(monkeypatch):
    module = _module()
    pem = "-----BEGIN EC PRIVATE KEY-----\nQUJDREVGRw==\n-----END EC PRIVATE KEY-----\n"
    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key-2")
    monkeypatch.setenv("COINBASE_API_SECRET", pem)

    class CoinbaseBroker:
        def __init__(self):
            self.connected = False
        def connect(self):
            self.connected = True
            return True
        def get_balance(self):
            return {"usd": 100.0, "usdc": 44.29}

    class CoinbaseBrokerAdapter(CoinbaseBroker):
        pass

    fake = types.ModuleType("bot.broker_manager")
    fake.CoinbaseBroker = CoinbaseBroker
    fake.CoinbaseBrokerAdapter = CoinbaseBrokerAdapter
    assert module._patch_broker_module(fake) is True

    broker = CoinbaseBroker()
    assert broker.connect() is True
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "1"
    assert os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] == "1"
    assert float(os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"]) == 144.29
