from __future__ import annotations

import base64
import importlib
import json
import os


_SECRET_ALIASES = (
    "COINBASE_API_SECRET",
    "COINBASE_PLATFORM_API_SECRET",
    "COINBASE_ADVANCED_API_SECRET",
    "COINBASE_PEM_CONTENT",
    "COINBASE_API_PRIVATE_KEY",
    "COINBASE_PRIVATE_KEY",
    "COINBASE_CDP_API_SECRET",
    "CDP_API_KEY_PRIVATE_KEY",
)
_KEY_ALIASES = (
    "COINBASE_API_KEY",
    "COINBASE_PLATFORM_API_KEY",
    "COINBASE_ADVANCED_API_KEY",
    "COINBASE_CDP_API_KEY",
    "CDP_API_KEY_NAME",
)


def _module():
    return importlib.reload(importlib.import_module("secondary_venue_runtime_diagnostics"))


def _clear_coinbase_aliases(monkeypatch):
    for name in _SECRET_ALIASES + _KEY_ALIASES + (
        "NIJA_COINBASE_PEM_STATE",
        "NIJA_COINBASE_PEM_VALID",
        "NIJA_COINBASE_PEM_QUARANTINED",
        "NIJA_COINBASE_PEM_INVALID_REASON",
    ):
        monkeypatch.delenv(name, raising=False)


def test_normalize_coinbase_private_key_restores_escaped_newlines(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    raw = '"-----BEGIN EC PRIVATE KEY-----\\nABC\\n-----END EC PRIVATE KEY-----"'
    normalized = module.normalize_coinbase_private_key(raw)
    assert normalized == "-----BEGIN EC PRIVATE KEY-----\nABC\n-----END EC PRIVATE KEY-----\n"


def test_normalize_coinbase_private_key_decodes_json_and_base64(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    pem = "-----BEGIN EC PRIVATE KEY-----\nABC\n-----END EC PRIVATE KEY-----\n"
    json_secret = json.dumps({"privateKey": pem.replace("\n", "\\n")})
    encoded = base64.b64encode(pem.encode("utf-8")).decode("ascii")

    assert module.normalize_coinbase_private_key(json_secret) == pem
    assert module.normalize_coinbase_private_key(encoded) == pem


def test_missing_coinbase_secret_is_fail_closed(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    module = _module()
    module._normalize_coinbase_env()
    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "missing"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "0"
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "0"


def test_invalid_cdp_secret_is_quarantined_without_blocking_other_venues(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    monkeypatch.setenv("COINBASE_API_KEY", "organizations/example/apiKeys/example")
    monkeypatch.setenv("COINBASE_API_SECRET", "not-a-pem")
    monkeypatch.setenv("ENABLE_COINBASE_TRADING", "true")
    monkeypatch.setenv("COINBASE_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("NIJA_DISABLE_COINBASE", "false")

    module = _module()
    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "invalid"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "0"
    assert os.environ["NIJA_COINBASE_PEM_QUARANTINED"] == "1"
    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "quarantined_invalid_pem"
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "0"
    assert os.environ["NIJA_DISABLE_COINBASE"] == "true"
    assert os.environ["ENABLE_COINBASE_TRADING"] == "false"
    assert os.environ["COINBASE_LIVE_TRADING_ENABLED"] == "false"
    assert os.environ["NIJA_COINBASE_PEM_INVALID_REASON"] == "validation_failed"


def test_existing_cdp_aliases_are_normalized_and_synchronized(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    monkeypatch.setenv("CDP_API_KEY_NAME", "organizations/example/apiKeys/example")
    monkeypatch.setenv(
        "CDP_API_KEY_PRIVATE_KEY",
        "-----BEGIN EC PRIVATE KEY-----\\nVALIDCDP\\n-----END EC PRIVATE KEY-----",
    )
    module = _module()
    monkeypatch.setattr(
        module,
        "_validate_coinbase_key",
        lambda secret: ("VALIDCDP" in secret, "valid_es256"),
    )

    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "valid"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "1"
    assert "VALIDCDP" in os.environ["COINBASE_API_SECRET"]
    assert all(os.environ[name] == os.environ["COINBASE_API_SECRET"] for name in _SECRET_ALIASES)


def test_malformed_base64_wrapped_pem_is_not_misclassified_as_legacy(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    malformed_pem = (
        "-----BEGIN EC PRIVATE KEY-----\n"
        + ("NOTVALID" * 20)
        + "\n-----END EC PRIVATE KEY-----\n"
    )
    monkeypatch.setenv("COINBASE_API_KEY", "legacy-shaped-key")
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        base64.b64encode(malformed_pem.encode("utf-8")).decode("ascii"),
    )
    module = _module()

    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "invalid"
    assert os.environ["NIJA_COINBASE_PEM_QUARANTINED"] == "1"
    assert os.environ["NIJA_DISABLE_COINBASE"] == "true"


def test_later_valid_alias_wins_over_stale_primary_alias(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    monkeypatch.setenv("COINBASE_API_KEY", "organizations/example/apiKeys/example")
    monkeypatch.setenv("COINBASE_API_SECRET", "stale-broken-secret")
    monkeypatch.setenv(
        "COINBASE_PLATFORM_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\\nVALID\\n-----END EC PRIVATE KEY-----",
    )
    module = _module()
    monkeypatch.setattr(
        module,
        "_validate_coinbase_key",
        lambda secret: ("VALID" in secret, "valid_es256" if "VALID" in secret else "invalid"),
    )

    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "valid"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "1"
    assert os.environ["NIJA_COINBASE_PEM_QUARANTINED"] == "0"
    assert "VALID" in os.environ["COINBASE_API_SECRET"]
    assert all(os.environ[name] == os.environ["COINBASE_API_SECRET"] for name in _SECRET_ALIASES)


def test_non_cdp_legacy_secret_is_not_falsely_quarantined(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    monkeypatch.setenv("COINBASE_API_KEY", "legacy-key")
    monkeypatch.setenv("COINBASE_API_SECRET", "legacy-hmac-secret")
    module = _module()

    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "legacy_unverified"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "0"
    assert os.environ.get("NIJA_COINBASE_PEM_QUARANTINED") != "1"


def test_quarantine_state_is_restored_after_generic_activation_skip(monkeypatch):
    module = importlib.import_module("secondary_venue_runtime_diagnostics")
    monkeypatch.setenv("NIJA_COINBASE_PEM_QUARANTINED", "1")
    monkeypatch.setenv("NIJA_COINBASE_PEM_STATE", "valid")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "disabled")
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_DISABLE_COINBASE", "false")
    monkeypatch.setenv("ENABLE_COINBASE_TRADING", "true")
    monkeypatch.setenv("COINBASE_LIVE_TRADING_ENABLED", "true")

    module._restore_coinbase_quarantine_state()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "invalid"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "0"
    assert os.environ["NIJA_COINBASE_ACTIVATION_STATE"] == "quarantined_invalid_pem"
    assert os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert os.environ["NIJA_COINBASE_TRADING_READY"] == "0"
    assert os.environ["NIJA_DISABLE_COINBASE"] == "true"
    assert os.environ["ENABLE_COINBASE_TRADING"] == "false"
    assert os.environ["COINBASE_LIVE_TRADING_ENABLED"] == "false"


def test_valid_coinbase_secret_does_not_override_operator_disable_state(monkeypatch):
    _clear_coinbase_aliases(monkeypatch)
    monkeypatch.setenv(
        "COINBASE_API_SECRET",
        "-----BEGIN EC PRIVATE KEY-----\\nABC\\n-----END EC PRIVATE KEY-----",
    )
    monkeypatch.setenv("NIJA_DISABLE_COINBASE", "true")
    module = _module()
    monkeypatch.setattr(module, "_validate_coinbase_key", lambda _secret: (True, "valid_es256"))

    module._normalize_coinbase_env()

    assert os.environ["NIJA_COINBASE_PEM_STATE"] == "valid"
    assert os.environ["NIJA_COINBASE_PEM_VALID"] == "1"
    assert os.environ["NIJA_COINBASE_PEM_QUARANTINED"] == "0"
    assert os.environ["NIJA_DISABLE_COINBASE"] == "true"
