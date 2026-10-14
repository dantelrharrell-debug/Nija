"""Offline guardrails for legacy membership reconciliation."""
import unittest
from legacy_membership_binding_preflight import check_legacy_binding


class LegacyBindingTests(unittest.TestCase):
    def evidence(self, **changes):
        data = dict(
            user_id="application-123", application_user_id="application-123",
            verified_email="verified@example.com", application_email="verified@example.com",
            authenticated_email="verified@example.com",
            stripe_customer_id="cus_existing", subscription_customer_id="cus_existing",
            subscription_id="sub_existing", subscription_status="trialing",
            expected_price_id="price_founding", actual_price_id="price_founding",
            existing_subscription_owner=None, existing_customer_owner=None,
            identity_proof_complete=True, application_ownership_verified=True,
        )
        data.update(changes)
        return check_legacy_binding(**data)

    def test_valid_preflight_is_not_entitlement(self):
        self.assertTrue(self.evidence().verified)

    def test_requires_independent_identity_ownership(self):
        self.assertFalse(self.evidence(application_ownership_verified=False).verified)
        self.assertFalse(self.evidence(identity_proof_complete=False).verified)

    def test_rejects_mismatched_email(self):
        for value in ("other@example.com", "", "bad"):
            with self.subTest(value=value):
                self.assertIn("verified_email_mismatch", self.evidence(
                    authenticated_email=value).reasons)
        self.assertFalse(self.evidence(application_email="another@example.com").verified)

    def test_rejects_foreign_customer_and_subscription(self):
        self.assertIn("subscription_already_bound", self.evidence(
            existing_subscription_owner="other-user").reasons)
        self.assertIn("customer_already_bound", self.evidence(
            existing_customer_owner="other-user").reasons)
        self.assertFalse(self.evidence(subscription_customer_id="cus_other").verified)

    def test_rejects_unpaid_or_wrong_product(self):
        self.assertFalse(self.evidence(subscription_status="past_due").verified)
        self.assertFalse(self.evidence(actual_price_id="price_wrong").verified)


if __name__ == "__main__":
    unittest.main()
