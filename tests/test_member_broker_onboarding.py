"""Contract tests: no trading runtime and no real broker secrets."""
import unittest
from bot.member_broker_vault import VaultError
from bot.member_broker_onboarding import MemberBrokerOnboarding


class FakeVault:
    def __init__(self):
        self.rows = []
        self.created = []
    def list_metadata(self, token):
        if token != "valid-member-token":
            raise VaultError("Unauthorized")
        return self.rows
    def create(self, token, broker, environment, credentials):
        if token != "valid-member-token":
            raise VaultError("Unauthorized")
        self.created.append((broker, environment, dict(credentials)))
        return "record-id"


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.vault = FakeVault()
        self.flow = MemberBrokerOnboarding(self.vault, secret_intake_enabled=True)

    def test_secure_connection_does_not_return_keys(self):
        result = self.flow.connect("valid-member-token", "kraken", "live",
                                   {"api_key": "fake-key", "api_secret": "fake-secret"})
        self.assertEqual((result.broker, result.environment, result.credentials_stored, result.connected),
                         ("kraken", "live", True, False))
        self.assertFalse(result.broker_verified)
        self.assertFalse(result.live_trading_authorized)
        self.assertNotIn("fake-key", repr(result))
        self.assertNotIn("fake-secret", repr(result))

    def test_all_nija_brokers_store_only_without_verification(self):
        examples = {
            "kraken": {"api_key": "fake", "api_secret": "fake"},
            "alpaca": {"api_key": "fake", "api_secret": "fake"},
            "coinbase": {"api_key": "organizations/fake/apiKeys/fake", "api_secret": "fake-private-key"},
            "okx": {"api_key": "fake", "api_secret": "fake", "passphrase": "fake"},
        }
        for broker, credentials in examples.items():
            with self.subTest(broker=broker):
                result = self.flow.connect("valid-member-token", broker, "paper", credentials)
                self.assertTrue(result.credentials_stored)
                self.assertFalse(result.broker_verified)
                self.assertFalse(result.live_trading_authorized)
                self.assertNotIn("fake-private-key", repr(result))

    def test_okx_requires_passphrase(self):
        with self.assertRaises(VaultError):
            self.flow.connect("valid-member-token", "okx", "paper",
                              {"api_key": "fake", "api_secret": "fake"})
        self.assertFalse(self.vault.created)

    def test_coinbase_rejects_unexpected_credential_fields(self):
        with self.assertRaises(VaultError):
            self.flow.connect("valid-member-token", "coinbase", "paper",
                              {"api_key": "fake", "api_secret": "fake", "passphrase": "extra"})
        self.assertFalse(self.vault.created)

    def test_secret_intake_disabled_by_default(self):
        disabled = MemberBrokerOnboarding(self.vault)
        with self.assertRaisesRegex(VaultError, "not enabled"):
            disabled.connect("valid-member-token", "kraken", "paper",
                             {"api_key": "fake", "api_secret": "fake"})
        self.assertFalse(self.vault.created)

    def test_preexisting_scope_rejected_before_creating_more_secrets(self):
        self.vault.rows = [{"id": "existing", "broker": "kraken", "environment": "live"}]
        with self.assertRaisesRegex(VaultError, "already exists"):
            self.flow.connect("valid-member-token", "kraken", "live",
                              {"api_key": "fake", "api_secret": "fake"})
        self.assertFalse(self.vault.created)

    def test_invalid_identity_fails_closed(self):
        with self.assertRaises(VaultError):
            self.flow.connect("invalid", "alpaca", "paper",
                              {"api_key": "fake", "api_secret": "fake"})
        self.assertFalse(self.vault.created)

    def test_unrecognized_fields_rejected(self):
        for credentials in ({"api_key": "fake"}, {"api_key": "fake", "api_secret": "fake", "withdraw": "true"}):
            with self.assertRaises(VaultError):
                self.flow.connect("valid-member-token", "kraken", "live", credentials)
        self.assertFalse(self.vault.created)

    def test_duplicate_connection_fails_closed(self):
        self.vault.rows = [
            {"id": "a", "broker": "kraken", "environment": "live"},
            {"id": "b", "broker": "kraken", "environment": "live"},
        ]
        with self.assertRaises(VaultError):
            self.flow.connections("valid-member-token")

    def test_connection_listing_exposes_metadata_only(self):
        self.vault.rows = [{"id": "a", "broker": "alpaca", "environment": "paper", "ciphertext": "opaque"}]
        result = self.flow.connections("valid-member-token")
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].credentials_stored)
        self.assertFalse(result[0].connected)
        self.assertNotIn("opaque", repr(result))


if __name__ == "__main__":
    unittest.main()
