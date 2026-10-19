"""No-real-secret tests for external member credential HTTP service."""
import unittest
from unittest.mock import patch
from member_broker_onboarding import MemberBrokerOnboarding
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
            "NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_BILLING_ENTITLEMENT_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED": "true",
        }
        with patch.dict("os.environ", required):
            self.assertEqual(app.test_client().get("/readyz").status_code, 200)
            for key in required:
                with patch.dict("os.environ", {key: ""}):
                    self.assertEqual(app.test_client().get("/readyz").status_code, 503)

    def test_readiness_requires_independent_security_verification(self):
        enabled = MemberBrokerOnboarding(FakeVault(), secret_intake_enabled=True)
        app = create_app(onboarding=enabled)
        configured = {
            "NIJA_VAULT_BILLING_READONLY_URL": "postgresql://test-only",
            "NIJA_VAULT_STRIPE_READONLY_KEY": "test-only",
            "NIJA_VAULT_FOUNDING_PRICE_ID": "price_test",
            "NIJA_VAULT_FOUNDING_PRODUCT_ID": "prod_test",
            "NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_BILLING_ENTITLEMENT_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED": "true",
        }
        with patch.dict("os.environ", configured):
            self.assertEqual(app.test_client().get("/readyz").status_code, 200)
            for name in ("NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED",
                         "NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED",
                         "NIJA_MEMBER_BROKER_BILLING_ENTITLEMENT_VERIFIED",
                         "NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED"):
                for value in ("", "false", "TRUE"):
                    with patch.dict("os.environ", {name: value}):
                        self.assertEqual(app.test_client().get("/readyz").status_code, 503)

    def test_readiness_logs_only_fixed_non_secret_blocker(self):
        import logging
        from unittest.mock import Mock
        from member_broker_http_api import _readiness_blocker

        enabled = MemberBrokerOnboarding(FakeVault(), secret_intake_enabled=True)
        settings = {
            "NIJA_VAULT_BILLING_READONLY_URL": "synthetic-private-billing-url",
            "NIJA_VAULT_STRIPE_READONLY_KEY": "synthetic-private-key",
            "NIJA_VAULT_FOUNDING_PRICE_ID": "synthetic-price",
            "NIJA_VAULT_FOUNDING_PRODUCT_ID": "synthetic-product",
            "NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_BILLING_ENTITLEMENT_VERIFIED": "true",
            "NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED": "true",
        }
        with patch.dict("os.environ", settings, clear=True):
            self.assertEqual(_readiness_blocker(None), "vault_unavailable")
            self.assertIsNone(_readiness_blocker(enabled))
            self.assertEqual(_readiness_blocker(MemberBrokerOnboarding(FakeVault())),
                             "capabilities_disabled")
            with patch.dict("os.environ", {"NIJA_VAULT_STRIPE_READONLY_KEY": ""}):
                self.assertEqual(_readiness_blocker(enabled),
                                 "billing_configuration_incomplete")
            with patch.dict("os.environ",
                            {"NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED": "false"}):
                self.assertEqual(_readiness_blocker(enabled),
                                 "security_review_incomplete")
            with patch("member_broker_http_api.LOGGER.warning") as warning:
                with patch.dict("os.environ", {"NIJA_VAULT_STRIPE_READONLY_KEY": ""}):
                    response = create_app(onboarding=enabled).test_client().get("/readyz")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json(), {"status": "not_ready"})
                self.assertEqual(warning.call_args.args,
                                 ("MEMBER_BROKER_READINESS ready=false reason=%s",
                                  "billing_configuration_incomplete"))
                self.assertNotIn(b"synthetic-private", response.data)

    def test_vault_init_error_logs_type_without_exception_secret(self):
        with patch("member_broker_http_api.BrokerVault.from_environment",
                   side_effect=ValueError("synthetic-private-key")):
            with patch("member_broker_http_api.LOGGER.warning") as warning:
                response = create_app().test_client().get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "not_ready"})
        self.assertEqual(warning.call_args_list[0].args,
                         ("MEMBER_BROKER_VAULT_INIT_FAILED reason=vault_unavailable error_type=%s",
                          "ValueError"))
        self.assertNotIn("synthetic-private-key", str(warning.call_args_list))

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
