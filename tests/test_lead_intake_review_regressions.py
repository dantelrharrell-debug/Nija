"""Regression coverage for nested website lead intake and identity precedence."""

import io
import json
import sqlite3
import unittest
from unittest.mock import patch

import render_lead_intake as intake
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


    def test_sqlite_lead_store_failure_fails_closed_without_forwarding(self):
        # Synthetic input only; no live website, CRM, email, or broker calls.
        raw = json.dumps({
            "form_name": "free_assessment",
            "email": "synthetic-qa@example.com",
            "event_id": "offline-only-1",
        }).encode("utf-8")

        class Handler:
            path = "/api/leads/intake"
            headers = {"Content-Length": str(len(raw))}

            def __init__(self):
                self.rfile = io.BytesIO(raw)
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, *_):
                pass

            def end_headers(self):
                pass

        handler = Handler()
        with (
            patch.object(intake, "_authorized", return_value=(True, 200, "ok")),
            patch.object(intake, "record_lead",
                         side_effect=sqlite3.OperationalError("private database diagnostic")),
            patch.object(intake, "_claim_forward",
                         side_effect=AssertionError("no delivery after failed persistence")),
        ):
            self.assertTrue(intake.handle_lead_intake_post(handler))

        self.assertEqual(handler.status, 503)
        self.assertEqual(json.loads(handler.wfile.getvalue()),
                         {"error": "Lead store unavailable"})
        self.assertNotIn(b"private database diagnostic", handler.wfile.getvalue())


    def test_source_event_id_alias_is_preserved_without_fabrication(self):
        payload = {
            "form_name": "free_assessment", "email": "test@example.invalid",
            "source_event_id": "website-stable-1",
            "internal_id": "",
            "submitted_at": "2026-11-13T12:00:00Z",
        }
        self.assertEqual(intake._source_event_id(payload), "website-stable-1")
        self.assertEqual(
            normalize_lead_payload(payload)["source_event_id"], "website-stable-1"
        )

    def test_matching_upstream_aliases_across_wrappers(self):
        payload = {
            "event_id": "evt-identical",
            "submission": {"data": {"submission_id": "evt-identical"}},
            "email": "test@example.invalid",
        }
        self.assertEqual(intake._source_event_id(payload), "evt-identical")

    def test_conflicting_upstream_ids_fail_closed(self):
        payload = {
            "email": "test@example.invalid",
            "event_id": "event-first",
            "submission_id": "event-second",
        }
        with self.assertRaisesRegex(ValueError, "Conflicting upstream submission IDs"):
            normalize_lead_payload(payload)

    def test_conflicting_wrapped_source_ids_fail_closed(self):
        payload = {
            "email": "test@example.invalid",
            "submission_id": "source-A",
            "data": {"source_event_id": "source-B"},
        }
        with self.assertRaisesRegex(ValueError, "Conflicting upstream submission IDs"):
            normalize_lead_payload(payload)

    def test_upstream_id_bool_and_dict_rejected(self):
        for bad in (True, {"id": "not-scalar"}, ["not-scalar"]):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "must be scalar"):
                    intake._source_event_id({
                        "email": "test@example.invalid", "submission_id": bad
                    })

    def test_oversized_upstream_id_is_rejected_not_truncated(self):
        with self.assertRaisesRegex(ValueError, "too long"):
            intake._source_event_id({
                "email": "test@example.invalid",
                "source_event_id": "x" * 161,
            })

    def test_legacy_internal_id_is_not_treated_as_authoritative(self):
        self.assertEqual(intake._source_event_id({
            "email": "test@example.invalid", "internal_id": "different-system-id",
        }), "")

if __name__ == "__main__":
    unittest.main()
