from __future__ import annotations

import base64
import importlib
import os


def test_normalize_coinbase_private_key_restores_escaped_newlines(monkeypatch):
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    raw = '"-----BEGIN EC PRIVATE KEY-----\\nABC\\n-----END EC PRIVATE KEY-----"'
    normalized = module.normalize_coinbase_private_key(raw)
    assert normalized == "-----BEGIN EC PRIVATE KEY-----\nABC\n-----END EC PRIVATE KEY-----\n"


def test_normalize_coinbase_private_key_decodes_base64_wrapped_pem(monkeypatch):
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    pem = "-----BEGIN PRIVATE KEY-----\nQUJDRA==\n-----END PRIVATE KEY-----\n"
    encoded = base64.b64encode(pem.encode("utf-8")).decode("ascii")
    assert module.normalize_coinbase_private_key(encoded) == pem


def test_normalize_coinbase_private_key_rewraps_collapsed_body(monkeypatch):
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    raw = "-----BEGIN PRIVATE KEY-----QUJDRA==-----END PRIVATE KEY-----"
    assert module.normalize_coinbase_private_key(raw) == (
        "-----BEGIN PRIVATE KEY-----\nQUJDRA==\n-----END PRIVATE KEY-----\n"
    )


def test_valid_key_synchronizes_all_aliases(monkeypatch):
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    aliases = (
        "COINBASE_API_SECRET",
        "COINBASE_PLATFORM_API_SECRET",
        "COINBASE_ADVANCED_API_SECRET",
        "COINBASE_API_PRIVATE_KEY",
        "COINBASE_PRIVATE_KEY",
        "COINBASE_PEM_CONTENT",
    )
    for name in aliases:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COINBASE_API_SECRET", "encoded-value")
    monkeypatch.setattr(
        module,
        "normalize_coinbase_private_key",
        lambda value: "-----BEGIN PRIVATE KEY-----\nVALID\n-----END PRIVATE KEY-----\n",
    )
    monkeypatch.setattr(module, "_validate_coinbase_key", lambda value: (True, "valid_es256"))

    module._normalize_coinbase_env()

    expected = "-----BEGIN PRIVATE KEY-----\nVALID\n-----END PRIVATE KEY-----\n"
    assert all(os.environ[name] == expected for name in aliases)
    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "valid"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "1"


def test_missing_coinbase_secret_is_fail_closed(monkeypatch):
    for name in (
        "COINBASE_API_SECRET",
        "COINBASE_PLATFORM_API_SECRET",
        "COINBASE_ADVANCED_API_SECRET",
        "COINBASE_API_PRIVATE_KEY",
        "COINBASE_PRIVATE_KEY",
        "COINBASE_PEM_CONTENT",
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
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "0"
