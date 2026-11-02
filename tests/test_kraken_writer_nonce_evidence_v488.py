"""Offline fail-closed checks for pinned, read-only Kraken writer evidence."""
import hashlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

if "bot" not in sys.modules:
    package = types.ModuleType("bot")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = package

from bot.kraken_writer_nonce_evidence_v488 import (
    KrakenWriterEvidenceDenied, make_kraken_writer_nonce_providers,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate

KEY = "synthetic-test-only-key"
SCOPE = "platform:kraken"
KEY_ID = hashlib.sha256(KEY.encode()).hexdigest()[:16]
IDS = {"writer_lease": "approved-writer", "nonce_sequence": "approved-nonce"}


class Manager:
    _redis = object()
    _strict_redis_lease = True
    _owner_id = "owner"
    _owner_fingerprint = "fingerprint"
    lease_version = 17

    def __init__(self):
        self.nonce = 100000

    def get_writer_lease_status(self, key):
        assert key == KEY_ID
        return {"enabled": True, "key_id": key, "error": "", "owner_id": "owner",
                "owner_fingerprint": "fingerprint", "token": 17,
                "ttl_remaining_ms": 25000, "stable_for_s": 12.0}

    def get_last_nonce(self, key):
        assert key == KEY_ID
        return self.nonce


class Broker:
    connected = True
    account_type = "platform"
    broker_type = "kraken"
    user_id = None
    api_key = KEY
    _gateway_url = ""
    _gateway_only_mode = False
    _nonce_key_id = KEY_ID
    _nonce_lease_version = 17

    def __init__(self):
        self._distributed_nonce_manager = Manager()
        self._kraken_private_call_nonce = lambda: 1
        self.api = types.SimpleNamespace(key=KEY, _nonce=self._kraken_private_call_nonce)


def build(broker):
    return make_kraken_writer_nonce_providers(
        broker, account_scope=SCOPE,
        approved_api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
        reviewed_provider_ids=IDS, independently_reviewed=True,
        clock=lambda: 1000.0,
    )


class TestWriterNonceEvidence(unittest.TestCase):
    def test_valid_runtime_yields_only_two_diagnostic_fields(self):
        broker = Broker()
        with patch("bot.execution_authority_context.assert_distributed_writer_authority"):
            providers = build(broker)
            self.assertEqual(set(providers), {"writer_lease", "nonce_sequence"})
            rows = {field: observe() for field, observe in providers.items()}
        self.assertTrue(all(row["verified"] is True for row in rows.values()))
        self.assertTrue(all(row["authorizes_orders"] is False for row in rows.values()))
        self.assertNotIn(KEY, str(rows))
        trusted = {field: "approved-" + field for field in REQUIRED}
        trusted.update(IDS)
        cert = evaluate_pretrade_certificate(
            rows, account=SCOPE, trusted_provider_ids=trusted, now_epoch=1000.0)
        self.assertFalse(cert["certified"])
        self.assertFalse(cert["authorizes_orders"])
        self.assertIn("position_ledger_reconciliation", cert["missing"])

    def test_requires_independent_review(self):
        with self.assertRaises(KrakenWriterEvidenceDenied):
            make_kraken_writer_nonce_providers(
                Broker(), account_scope=SCOPE,
                approved_api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
                reviewed_provider_ids=IDS)

    def test_disconnected_key_or_nonce_owner_denied(self):
        for change in ("connected", "key", "redis", "token", "generator", "canonical_missing"):
            broker = Broker()
            if change == "connected":
                broker.connected = False
            elif change == "key":
                broker.api.key = "other"
            elif change == "redis":
                broker._distributed_nonce_manager._redis = None
            elif change == "token":
                broker._nonce_lease_version = 18
            elif change == "canonical_missing":
                del broker._kraken_private_call_nonce
            else:
                broker.api._nonce = lambda: 1
            with self.subTest(change=change), patch(
                    "bot.execution_authority_context.assert_distributed_writer_authority"):
                with self.assertRaises(KrakenWriterEvidenceDenied):
                    build(broker)["writer_lease"]()

    def test_nonce_regression_denied(self):
        broker = Broker()
        counter = iter([100, 99])
        broker._distributed_nonce_manager.get_last_nonce = lambda _: next(counter)
        with patch("bot.execution_authority_context.assert_distributed_writer_authority"):
            with self.assertRaises(KrakenWriterEvidenceDenied):
                build(broker)["nonce_sequence"]()

    def test_failed_canonical_fence_denied(self):
        with patch("bot.execution_authority_context.assert_distributed_writer_authority",
                   side_effect=RuntimeError("lost")):
            with self.assertRaises(KrakenWriterEvidenceDenied):
                build(Broker())["writer_lease"]()

    def test_client_replacement_during_read_rejects_old_nonce_evidence(self):
        broker = Broker()
        original_status = broker._distributed_nonce_manager.get_writer_lease_status

        def replace_client(key):
            broker.api = types.SimpleNamespace(key=KEY, _nonce=broker._kraken_private_call_nonce)
            return original_status(key)

        broker._distributed_nonce_manager.get_writer_lease_status = replace_client
        with patch("bot.execution_authority_context.assert_distributed_writer_authority"):
            with self.assertRaisesRegex(KrakenWriterEvidenceDenied, "writer_evidence_changed_or_stale"):
                build(broker)["writer_lease"]()


if __name__ == "__main__":
    unittest.main()
