from __future__ import annotations

import importlib.util
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "coinbase_pem_quarantine_under_test",
        BOT_DIR / "coinbase_pem_quarantine_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_private_key_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_literal_newlines_are_normalized_and_valid_key_is_accepted():
    module = _load()
    pem = _valid_private_key_pem()

    class CoinbaseBroker:
        api_key = "organizations/test/apiKeys/test"
        api_secret = pem.replace("\n", "\\n")
        connected = False
        client = None

    broker = CoinbaseBroker()
    allowed, reason = module._preflight(broker)
    assert allowed is True
    assert reason == "pem_parse_ok"
    assert "\\n" not in broker.api_secret
    assert broker.api_secret.startswith("-----BEGIN PRIVATE KEY-----\n")


def test_malformed_key_is_quarantined_without_touching_other_brokers():
    module = _load()

    class CoinbaseBroker:
        api_key = "organizations/test/apiKeys/test"
        api_secret = "-----BEGIN PRIVATE KEY-----\\nnot-base64\\n-----END PRIVATE KEY-----"
        connected = True
        client = object()
        _last_known_balance = 123.0

    broker = CoinbaseBroker()
    allowed, reason = module._preflight(broker)
    assert allowed is False
    assert reason.startswith("pem_parse_failed:")
    assert broker.connected is False
    assert broker.client is None
    assert broker._last_known_balance == 0.0
    assert broker._nija_coinbase_config_quarantined is True


def test_quarantined_product_reader_returns_empty_instead_of_rethrowing_pem_error():
    module = _load()

    class CoinbaseBroker:
        api_key = "organizations/test/apiKeys/test"
        api_secret = "-----BEGIN PRIVATE KEY-----\\nbad\\n-----END PRIVATE KEY-----"
        connected = True
        client = object()

        def connect(self):
            raise ValueError("Unable to load PEM file: MalformedFraming")

        def get_all_products(self):
            raise ValueError("Unable to load PEM file: MalformedFraming")

    assert module._patch_class(CoinbaseBroker) is True
    broker = CoinbaseBroker()
    assert broker.connect() is False
    assert broker.get_all_products() == []
