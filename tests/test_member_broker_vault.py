"""Unit tests for isolated broker vault cryptography and fail-closed authorization."""
import base64
import json
import unittest
from unittest.mock import Mock

from bot.member_broker_vault import BrokerVault, VaultError


KEY = base64.b64encode(bytes(range(32))).decode()


class BrokerVaultTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.vault = BrokerVault("https://example.test", KEY, lambda user: user == "member123", session=self.session)

    def test_round_trip(self):
        encrypted = self.vault.encrypt("member123", "kraken", "live", {"api_key": "example", "secret": "sample"})
        self.assertNotIn("sample", encrypted)
        self.assertEqual(self.vault.decrypt("member123", "kraken", "live", encrypted)["secret"], "sample")

    def test_nonce_is_random(self):
        a = self.vault.encrypt("member123", "alpaca", "paper", {"key": "sample"})
        b = self.vault.encrypt("member123", "alpaca", "paper", {"key": "sample"})
        self.assertNotEqual(a, b)

    def test_aad_prevents_cross_scope_replay(self):
        encrypted = self.vault.encrypt("member123", "kraken", "live", {"key": "sample"})
        for scope in [("other", "kraken", "live"), ("member123", "alpaca", "live"), ("member123", "kraken", "paper")]:
            with self.assertRaises(VaultError):
                self.vault.decrypt(*scope, encrypted)

    def test_tampering_rejected(self):
        envelope = json.loads(self.vault.encrypt("member123", "kraken", "paper", {"key": "sample"}))
        c = bytearray(base64.b64decode(envelope["c"]))
        c[0] ^= 1
        envelope["c"] = base64.b64encode(c).decode()
        with self.assertRaises(VaultError):
            self.vault.decrypt("member123", "kraken", "paper", json.dumps(envelope))

    def test_invalid_broker_rejected(self):
        with self.assertRaises(VaultError):
            self.vault.encrypt("member123", "binance", "live", {"key": "sample"})

    def test_unverified_member_rejected_before_storage(self):
        self.session.request.return_value.status_code = 200
        self.session.request.return_value.json.return_value = {"record": {"id": "member123", "verified": False}}
        with self.assertRaises(VaultError):
            self.vault.create("member.jwt", "kraken", "live", {"key": "sample"})
        self.assertEqual(self.session.request.call_count, 1)

    def test_entitlement_rejected_before_storage(self):
        self.session.request.return_value.status_code = 200
        self.session.request.return_value.json.return_value = {"record": {"id": "no-plan", "verified": True}}
        with self.assertRaises(VaultError):
            self.vault.create("member.jwt", "kraken", "live", {"key": "sample"})
        self.assertEqual(self.session.request.call_count, 1)

    def test_backend_authentication_failure(self):
        self.session.request.return_value.status_code = 401
        with self.assertRaises(VaultError):
            self.vault.create("invalid.jwt", "kraken", "paper", {"key": "sample"})
        self.assertEqual(self.session.request.call_count, 1)

    def test_duplicate_write_conflict_does_not_retry(self):
        first = Mock(status_code=200)
        first.json.return_value = {"record": {"id": "member123", "verified": True}}
        conflict = Mock(status_code=400)
        self.session.request.side_effect = [first, conflict]
        with self.assertRaises(VaultError):
            self.vault.create("member.jwt", "alpaca", "live", {"key": "sample"})
        self.assertEqual(self.session.request.call_count, 2)

    def test_metadata_excludes_other_accounts_and_ciphertext(self):
        first = Mock(status_code=200)
        first.json.return_value = {"record": {"id": "member123", "verified": True}}
        second = Mock(status_code=200)
        second.json.return_value = {"totalPages": 1, "items": [
            {"id": "own", "user_id": "member123", "broker": "kraken", "environment": "paper", "ciphertext": "SECRET"},
            {"id": "other", "user_id": "member456", "broker": "alpaca", "environment": "live", "ciphertext": "SECRET"}
        ]}
        self.session.request.side_effect = [first, second]
        with self.assertRaises(VaultError):
            self.vault.list_metadata("member.jwt")

    def test_owned_metadata_strips_ciphertext(self):
        first = Mock(status_code=200)
        first.json.return_value = {"record": {"id": "member123", "verified": True}}
        second = Mock(status_code=200)
        second.json.return_value = {"totalPages": 1, "items": [
            {"id": "own", "user_id": "member123", "broker": "kraken", "environment": "paper", "ciphertext": "SECRET"}
        ]}
        self.session.request.side_effect = [first, second]
        self.assertEqual(self.vault.list_metadata("member.jwt"), [
            {"id": "own", "broker": "kraken", "environment": "paper"}
        ])

    def test_empty_vault_zero_pages_returns_empty_metadata(self):
        first = Mock(status_code=200)
        first.json.return_value = {'record': {'id': 'member123', 'verified': True}}
        second = Mock(status_code=200)
        second.json.return_value = {'totalPages': 0, 'items': []}
        self.session.request.side_effect = [first, second]
        self.assertEqual(self.vault.list_metadata('member.jwt'), [])

    def test_rejects_incomplete_metadata_pagination(self):
        first = Mock(status_code=200)
        first.json.return_value = {"record": {"id": "member123", "verified": True}}
        second = Mock(status_code=200)
        second.json.return_value = {"totalPages": 2, "items": []}
        self.session.request.side_effect = [first, second]
        with self.assertRaises(VaultError):
            self.vault.list_metadata("member.jwt")

    def test_key_must_be_256_bits_and_endpoint_https(self):
        with self.assertRaises(VaultError):
            BrokerVault("http://example.test", KEY, lambda uid: True)
        with self.assertRaises(VaultError):
            BrokerVault("https://example.test", base64.b64encode(b"short").decode(), lambda uid: True)

    def test_bad_base64_key_raises_vault_error(self):
        with self.assertRaises(VaultError):
            BrokerVault("https://example.test", "!not-base64!", lambda uid: True)

    def test_non_json_backend_response_fails_closed(self):
        self.session.request.return_value.status_code = 200
        self.session.request.return_value.json.side_effect = ValueError("bad json")
        with self.assertRaises(VaultError):
            self.vault.create("member.jwt", "kraken", "paper", {"key": "sample"})
        self.assertEqual(self.session.request.call_count, 1)

    def test_create_uses_authenticated_owner(self):
        first = Mock(status_code=200)
        first.json.return_value = {"record": {"id": "member123", "verified": True}}
        second = Mock(status_code=200)
        second.json.return_value = {"id": "vaultrecord"}
        self.session.request.side_effect = [first, second]
        self.assertEqual(self.vault.create("member.jwt", "kraken", "paper", {"key": "sample"}), "vaultrecord")
        payload = self.session.request.call_args.kwargs["json"]
        self.assertEqual(payload["user_id"], "member123")
        self.assertNotIn("sample", payload["ciphertext"])
        self.assertEqual(len(self.session.request.call_args_list), 2)


if __name__ == "__main__":
    unittest.main()
