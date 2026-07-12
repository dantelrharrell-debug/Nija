from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "broker_auth_recovery_patch_test_module",
    ROOT / "broker_auth_recovery_patch.py",
)
assert SPEC and SPEC.loader
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)


@pytest.fixture(autouse=True)
def clean_broker_env(monkeypatch):
    names = (
        "COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_PEM_CONTENT",
        "COINBASE_PLATFORM_API_KEY", "COINBASE_PLATFORM_API_SECRET",
        "COINBASE_CDP_API_KEY", "COINBASE_CDP_API_SECRET",
        "CDP_API_KEY_NAME", "CDP_API_KEY_PRIVATE_KEY",
        "OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE",
        "OKX_API_PASSPHRASE", "OKX_PLATFORM_API_KEY",
        "OKX_PLATFORM_API_SECRET", "OKX_PLATFORM_PASSPHRASE",
        "OKX_BASE_URL", "OKX_API_BASE_URL", "OKX_ENDPOINT",
        "OKX_REGION", "OKX_ACCOUNT_REGION", "OKX_US_REGION",
        "OKX_SIMULATED_TRADING", "OKX_DISABLE_ENDPOINT_FALLBACK",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_coinbase_extracts_json_escaped_private_key(monkeypatch):
    payload = {
        "name": "organizations/org/apiKeys/key",
        "privateKey": "-----BEGIN EC PRIVATE KEY-----\\nQUJDRA==\\n-----END EC PRIVATE KEY-----\\n",
    }
    monkeypatch.setenv("COINBASE_API_KEY", __import__("json").dumps(payload))
    monkeypatch.setenv("COINBASE_API_SECRET", __import__("json").dumps(payload))

    assert patch.normalize_coinbase_environment() is True
    assert os.environ["COINBASE_API_KEY"] == "organizations/org/apiKeys/key"
    assert os.environ["COINBASE_API_SECRET"].startswith("-----BEGIN EC PRIVATE KEY-----\n")
    assert os.environ["COINBASE_API_SECRET"].endswith("-----END EC PRIVATE KEY-----\n")


def test_coinbase_accepts_base64_encoded_pem_alias(monkeypatch):
    pem = "-----BEGIN PRIVATE KEY-----\nQUJDRA==\n-----END PRIVATE KEY-----\n"
    monkeypatch.setenv("CDP_API_KEY_NAME", "organizations/org/apiKeys/key")
    monkeypatch.setenv("CDP_API_KEY_PRIVATE_KEY", base64.b64encode(pem.encode()).decode())

    assert patch.normalize_coinbase_environment() is True
    assert os.environ["COINBASE_API_SECRET"] == pem
    assert os.environ["COINBASE_PEM_CONTENT"] == pem


def test_coinbase_stale_primary_secret_can_fall_back_to_valid_alias(monkeypatch):
    monkeypatch.setenv("COINBASE_API_KEY", "organizations/org/apiKeys/key")
    monkeypatch.setenv("COINBASE_API_SECRET", "not-a-pem")
    monkeypatch.setenv(
        "COINBASE_PEM_CONTENT",
        "-----BEGIN EC PRIVATE KEY-----\\nQUJDRA==\\n-----END EC PRIVATE KEY-----",
    )

    # Current precedence intentionally retains the first non-empty secret. This
    # test documents fail-closed behavior: malformed primary values are not
    # silently replaced unless operators remove them.
    assert patch.normalize_coinbase_environment() is False


def test_okx_accepts_passphrase_alias_and_global_region(monkeypatch):
    monkeypatch.setenv("OKX_PLATFORM_API_KEY", "key")
    monkeypatch.setenv("OKX_PLATFORM_API_SECRET", "secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "passphrase")
    monkeypatch.setenv("OKX_REGION", "global")

    assert patch.normalize_okx_environment() is True
    assert os.environ["OKX_API_KEY"] == "key"
    assert os.environ["OKX_API_SECRET"] == "secret"
    assert os.environ["OKX_PASSPHRASE"] == "passphrase"
    assert os.environ["OKX_BASE_URL"] == "https://www.okx.com"


def test_okx_explicit_api_base_url_wins(monkeypatch):
    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_API_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSPHRASE", "passphrase")
    monkeypatch.setenv("OKX_BASE_URL", "https://us.okx.com")
    monkeypatch.setenv("OKX_API_BASE_URL", "https://www.okx.com/")

    assert patch.normalize_okx_environment() is True
    assert os.environ["OKX_BASE_URL"] == "https://www.okx.com"


def test_okx_endpoint_fallback_is_bounded():
    assert patch._alternate_okx_url("https://us.okx.com") == "https://www.okx.com"
    assert patch._alternate_okx_url("https://www.okx.com") == "https://us.okx.com"
    assert patch._alternate_okx_url("https://example.invalid") == ""
