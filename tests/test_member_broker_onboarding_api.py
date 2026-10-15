"""No external services or credentials required for broker onboarding tests."""
import os
import unittest
from unittest.mock import patch, MagicMock

from bot.member_broker_onboarding_api import make_member_broker_blueprint


class MemberBrokerOnboardingTests(unittest.TestCase):
    def test_refuses_unverified_rules(self):
        with patch.dict(os.environ, {"NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED": "false"}):
            with self.assertRaises(RuntimeError):
                make_member_broker_blueprint(lambda user: True)

    def test_refuses_missing_entitlement_verifier(self):
        with patch.dict(os.environ, {"NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED": "true"}):
            with self.assertRaises(RuntimeError):
                make_member_broker_blueprint(None)

    def test_rejects_unauthorized_and_never_returns_secrets(self):
        from flask import Flask
        mocked = MagicMock()
        mocked.list_metadata.return_value = [{"id": "record1", "broker": "kraken", "environment": "paper"}]
        mocked.create.return_value = "record2"
        with patch.dict(os.environ, {"NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED": "true"}), patch(
            "bot.member_broker_onboarding_api.BrokerVault.from_environment", return_value=mocked
        ):
            app = Flask(__name__)
            app.register_blueprint(make_member_broker_blueprint(lambda user: True))
            client = app.test_client()
            self.assertEqual(client.get("/api/member/brokerages").status_code, 403)
            self.assertEqual(mocked.list_metadata.call_count, 0)
            response = client.get("/api/member/brokerages", headers={"Authorization": "Bearer member-token"})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["trading_enabled"])
            self.assertNotIn("ciphertext", response.get_data(as_text=True))
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(client.post("/api/member/brokerages", json={"broker": "kraken"}).status_code, 400)
            response = client.post("/api/member/brokerages", json={
                "broker": "kraken", "environment": "paper", "credentials": {"api_key": "test-only"}
            }, headers={"Authorization": "Bearer member-token"})
            self.assertEqual(response.status_code, 201)
            self.assertNotIn("test-only", response.get_data(as_text=True))
            self.assertFalse(response.json["trading_enabled"])


if __name__ == "__main__":
    unittest.main()
