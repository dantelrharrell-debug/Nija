"""Offline guardrails for legacy membership reconciliation."""
import unittest
from legacy_membership_binding_preflight import check_legacy_binding


class LegacyBindingTests(unittest.TestCase):
    def evidence(self, **changes):
        data = dict(
            user_id="application-123", application_user_id="application-123",
            verified_email="verified@example.com", stripe_customer_id="cus_existing",
            subscription_customer_id="cus_existing", subscription_id="sub_existing",
            subscription_status="trialing", expected_price_id="price_founding",
            actual_price_id="price_founding", existing_subscription_owner=None,
            existing_customer_owner=None, identity_proof_complete=True,
            application_ownership_verified=True,
        )
        data.update(changes)
        return check_legacy_binding(**data)

    def test_valid_preflight_is_only_evidence_not_entitlement(self):
        self.assertTrue(self.evidence().verified)

    def test_requires_explicit_application_ownership(self):
        result = self.evidence(application_ownership_verified=False)
        self.assertFalse(result.verified)
        self.assertIn("identity_ownership_unverified", result.reasons)

    def test_prevents_cross_customer_binding(self):
        result = self.evidence(existing_subscription_owner="other-user")
        self.assertFalse(result.verified)
        self.assertIn("subscription_already_bound", result.reasons)

    def test_rejects_unpaid_or_wrong_price(self):
        result = self.evidence(subscription_status="past_due", actual_price_id="price_wrong")
        self.assertFalse(result.verified)
        self.assertIn("subscription_not_entitled", result.reasons)
        self.assertIn("price_mismatch", result.reasons)


if __name__ == "__main__":
    unittest.main()
