"""No-real-secret tests for external member credential HTTP service."""
import unittest
from unittest.mock import patch
from bot.member_broker_onboarding import MemberBrokerOnboarding
from member_broker_http_api import create_app
from member_broker_entitlement import check_founding_entitlement


class FakeVault:
    def list_metadata(self, token):
        if token != "test-token":
            raise ValueError("denied")
        return []
    def create(self, token, broker, environment, credentials):
        if token != "test-token":
            raise ValueError("denied")
        return "dummy"


class MemberHTTPTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(onboarding=MemberBrokerOnboarding(FakeVault()))
        self.client = self.app.test_client()
        self.h = {"Origin": "https://nijaaitrading.com",
                  "Authorization": "Bearer test-token"}

    def test_health(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_readiness_fails_closed_without_billing_configuration(self):
        enabled = MemberBrokerOnboarding(FakeVault(), secret_intake_enabled=True)
        app = create_app(onboarding=enabled)
        with patch.dict("os.environ", {
            "NIJA_VAULT_BILLING_READONLY_URL": "",
            "NIJA_VAULT_STRIPE_READONLY_KEY": "",
            "NIJA_VAULT_FOUNDING_PRICE_ID": "",
            "NIJA_VAULT_FOUNDING_PRODUCT_ID": "",
        }):
            response = app.test_client().get("/readyz")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json(), {"status": "not_ready"})
            self.assertEqual(app.test_client().get("/healthz").status_code, 200)

    def test_readiness_requires_each_entitlement_setting(self):
        enabled = MemberBrokerOnboarding(FakeVault(), secret_intake_enabled=True)
        app = create_app(onboarding=enabled)
        required = {
            "NIJA_VAULT_BILLING_READONLY_URL": "postgresql://test-only",
            "NIJA_VAULT_STRIPE_READONLY_KEY": "test-only",
            "NIJA_VAULT_FOUNDING_PRICE_ID": "price_test",
            "NIJA_VAULT_FOUNDING_PRODUCT_ID": "prod_test",
        }
        with patch.dict("os.environ", required):
            self.assertEqual(app.test_client().get("/readyz").status_code, 200)
            for key in required:
                with patch.dict("os.environ", {key: ""}):
                    self.assertEqual(app.test_client().get("/readyz").status_code, 503)

    def test_no_intake_by_default(self):
        response = self.client.post("/api/member/brokers/connect", headers=self.h, json={
            "broker": "kraken", "environment": "paper",
            "credentials": {"api_key": "dummy-key", "api_secret": "dummy-secret"},
        })
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"dummy-secret", response.data)

    def test_get_never_claims_broker_live(self):
        response = self.client.get("/api/member/brokers", headers=self.h)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"connections": []})

    def test_wrong_origin_rejected(self):
        response = self.client.get(
            "/api/member/brokers",
            headers={"Origin": "https://malicious.example", "Authorization": "Bearer test-token"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_auth_required(self):
        response = self.client.get("/api/member/brokers",
                                   headers={"Origin": "https://nijaaitrading.com"})
        self.assertEqual(response.status_code, 401)

    def test_entitlement_fails_closed(self):
        self.assertFalse(check_founding_entitlement("member123"))
        row = {"nija_user_id": "member123", "offer_code": "founding_beta",
               "status": "trialing", "entitled": True,
               "expected_price_id": "price_1", "expected_product_id": "prod_1",
               "stripe_subscription_id": "sub_1", "stripe_customer_id": "cus_1",
               "current_period_end": 4_000_000_000}
        sub = {"id": "sub_1", "customer": "cus_1", "livemode": True,
               "status": "trialing", "current_period_end": 4_000_000_000,
               "metadata": {"nija_user_id": "member123", "nija_offer_code": "founding_beta"},
               "items": {"data": [{"quantity": 1,
                                   "price": {"id": "price_1", "product": "prod_1"}}]}}
        with patch.dict("os.environ",
                        {"NIJA_VAULT_FOUNDING_PRICE_ID": "price_1",
                         "NIJA_VAULT_FOUNDING_PRODUCT_ID": "prod_1"}):
            self.assertTrue(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=sub, now=2_000_000_000))
            row["entitled"] = 1  # PostgreSQL/SQLite integer-encoded TRUE
            self.assertTrue(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=sub, now=2_000_000_000))
            row["entitled"] = 0
            self.assertFalse(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=sub, now=2_000_000_000))
            row["entitled"] = True
            missing_metadata = dict(sub)
            missing_metadata["metadata"] = {}
            self.assertFalse(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=missing_metadata, now=2_000_000_000))
            alt = dict(sub)
            alt["current_period_end"] = None
            alt["items"] = {"data": [{"quantity": 1, "current_period_end": 4_000_000_000,
                                    "price": {"id": "price_1", "product": "prod_1"}}]}
            self.assertTrue(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=alt, now=2_000_000_000))
            alt["metadata"] = {"nija_user_id": "different", "nija_offer_code": "founding_beta"}
            self.assertFalse(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=alt, now=2_000_000_000))
            alt["metadata"] = {"nija_user_id": "member123", "nija_offer_code": "founding_beta"}
            alt["items"]["data"][0]["current_period_end"] = 1
            self.assertFalse(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=alt, now=2_000_000_000))
            sub["livemode"] = False
            self.assertFalse(check_founding_entitlement(
                "member123", ledger_row=row, stripe_subscription=sub, now=2_000_000_000))


if __name__ == "__main__":
    unittest.main()
