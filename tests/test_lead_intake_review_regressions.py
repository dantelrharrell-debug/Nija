"""Regression coverage for nested website lead intake and identity precedence."""

import unittest

from render_lead_intake import normalize_lead_payload


class LeadIntakeReviewRegressions(unittest.TestCase):
    def test_second_level_input_data_wrapper(self):
        lead = normalize_lead_payload({
            "submission": {"inputData": {
                "Email Address": "qa@example.com",
                "firstName": "Jane", "lastName": "Doe",
                "submissionId": "event-1", "marketingConsent": "yes",
            }}
        })
        self.assertEqual(lead["email"], "qa@example.com")
        self.assertEqual(lead["name"], "Jane Doe")
        self.assertEqual(lead["communications_consent"], "true")

    def test_conflicting_aliases_same_map(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            normalize_lead_payload({
                "data": {"email": "customer@example.com",
                         "Email Address": "other@example.com"}
            })

    def test_non_scalar_secondary_email_alias(self):
        with self.assertRaisesRegex(ValueError, "string"):
            normalize_lead_payload({
                "data": {"email": "customer@example.com",
                         "Email Address": {"value": "other@example.com"}}
            })

    def test_invalid_secondary_email_alias(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            normalize_lead_payload({
                "data": {"email": "customer@example.com",
                         "Email Address": "not-an-email"}
            })

    def test_customer_split_name_precedes_form_metadata(self):
        lead = normalize_lead_payload({
            "formName": {"name": "Lead Gate"},
            "data": {"email": "qa@example.com",
                     "firstName": "Jane", "lastName": "Doe"},
        })
        self.assertEqual(lead["name"], "Jane Doe")


if __name__ == "__main__":
    unittest.main()
