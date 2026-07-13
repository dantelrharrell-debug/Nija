from __future__ import annotations

import importlib
import os


def test_normalize_coinbase_private_key_restores_escaped_newlines(monkeypatch):
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    raw = '"-----BEGIN EC PRIVATE KEY-----\\nABC\\n-----END EC PRIVATE KEY-----"'
    normalized = module.normalize_coinbase_private_key(raw)
    assert normalized == "-----BEGIN EC PRIVATE KEY-----\nABC\n-----END EC PRIVATE KEY-----\n"


def test_missing_coinbase_secret_is_fail_closed(monkeypatch):
    for name in (
        "COINBASE_API_SECRET",
        "COINBASE_PLATFORM_API_SECRET",
        "COINBASE_ADVANCED_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    module = importlib.reload(importlib.import_module("secondary_venue_runtime_diagnostics"))
    module._normalize_coinbase_env()
    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "missing"


def test_invalid_coinbase_secret_is_not_marked_valid(monkeypatch):
    monkeypatch.setenv("COINBASE_API_SECRET", "not-a-pem")
    module = importlib.reload(importlib.import_module("secondary_venue_runtime_diagnostics"))
    module._normalize_coinbase_env()
    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "invalid"
