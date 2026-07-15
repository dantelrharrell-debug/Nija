from __future__ import annotations

import base64
import json

from bot import coinbase_funding_readiness_repair_patch as patch


def test_combined_json_recovers_key_and_private_key(monkeypatch):
    pem = "-----BEGIN EC PRIVATE KEY-----\nQUJDREVGRw==\n-----END EC PRIVATE KEY-----\n"
    monkeypatch.setenv(
        "COINBASE_CDP_CREDENTIALS",
        json.dumps({"name": "organizations/test/apiKeys/key", "privateKey": pem.replace("\n", "\\n")}),
    )
    monkeypatch.delenv("COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)

    assert patch.recover_coinbase_environment() is True
    assert patch.os.environ["COINBASE_API_KEY"] == "organizations/test/apiKeys/key"
    assert patch.os.environ["COINBASE_API_SECRET"].startswith("-----BEGIN EC PRIVATE KEY-----\n")
    assert patch.os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] == "0"
    assert patch.os.environ["NIJA_COINBASE_FUNDING_STATUS"] == "unobserved"


def test_base64_private_key_is_decoded(monkeypatch):
    pem = "-----BEGIN PRIVATE KEY-----\nQUJDREVGRw==\n-----END PRIVATE KEY-----\n"
    monkeypatch.setenv("COINBASE_API_KEY", "organizations/test/apiKeys/key")
    monkeypatch.setenv("COINBASE_API_SECRET", base64.b64encode(pem.encode()).decode())

    assert patch.recover_coinbase_environment() is True
    assert "BEGIN PRIVATE KEY" in patch.os.environ["COINBASE_API_SECRET"]


def test_spendable_payload_sums_usd_and_usdc():
    payload = {
        "usd": 100.0,
        "accounts": {"ignored": 1},
        "wallet": {"currency": "USDC", "available_balance": {"value": "44.29"}},
    }
    assert patch._spendable_from_payload(payload) == 144.29
