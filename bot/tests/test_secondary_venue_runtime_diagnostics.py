from __future__ import annotations

import importlib
import os


def _module():
    return importlib.reload(importlib.import_module("secondary_venue_runtime_diagnostics"))


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
        "COINBASE_PEM_CONTENT",
    ):
        monkeypatch.delenv(name, raising=False)
    module = _module()
    module._normalize_coinbase_env()
    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "missing"
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "0"


def test_invalid_coinbase_secret_is_quarantined_without_blocking_other_venues(monkeypatch):
    monkeypatch.setenv("COINBASE_API_SECRET", "not-a-pem")
    monkeypatch.setenv("ENABLE_COINBASE_TRADING", "true")
    monkeypatch.setenv("COINBASE_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("NIJA_DISABLE_COINBASE", "false")

    module = _module()
    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "invalid"
    assert os.environ["NIJA_COINBASE_PEM_QUARANTINED"] == "1"
    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "quarantined_invalid_pem"
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "0"
    assert os.environ["NIJA_DISABLE_COINBASE"] == "true"
    assert os.environ["ENABLE_COINBASE_TRADING"] == "false"
    assert os.environ["COINBASE_LIVE_TRADING_ENABLED"] == "false"
    assert os.environ["NIJA_COINBASE_PEM_INVALID_REASON"]


def test_quarantine_state_is_restored_after_generic_activation_skip(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_PEM_QUARANTINED", "1")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "disabled")
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_DISABLE_COINBASE", "false")
    monkeypatch.setenv("ENABLE_COINBASE_TRADING", "true")
    monkeypatch.setenv("COINBASE_LIVE_TRADING_ENABLED", "true")
    module = _module()

    module._restore_coinbase_quarantine_state()

    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "quarantined_invalid_pem"
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "0"
    assert os.environ["NIJA_DISABLE_COINBASE"] == "true"
    assert os.environ["ENABLE_COINBASE_TRADING"] == "false"
    assert os.environ["COINBASE_LIVE_TRADING_ENABLED"] == "false"


def test_valid_coinbase_secret_does_not_override_operator_disable_state(monkeypatch):
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\\nABC\\n-----END EC PRIVATE KEY-----",
    )
    monkeypatch.setenv("NIJA_DISABLE_COINBASE", "true")
    module = _module()
    monkeypatch.setattr(module, "_validate_coinbase_key", lambda _secret: (True, "valid_es256"))

    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "valid"
    assert os.environ["NIJA_COINBASE_PEM_QUARANTINED"] == "0"
    assert os.environ["NIJA_DISABLE_COINBASE"] == "true"
