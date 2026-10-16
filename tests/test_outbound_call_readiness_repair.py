from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import importlib


class ApolloEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feeder = importlib.import_module("render_apollo_feeder")

    def _field_env(self):
        return mock.patch.dict(
            os.environ,
            {
                "NIJA_APOLLO_CONSENT_FIELD_ID": "consent-field",
                "NIJA_APOLLO_CONSENT_RECORD_FIELD_ID": "consent-record-field",
                "NIJA_APOLLO_LEGAL_BASIS_FIELD_ID": "legal-basis-field",
                "NIJA_APOLLO_DNC_STATUS_FIELD_ID": "dnc-status-field",
                "NIJA_APOLLO_DNC_CHECKED_AT_FIELD_ID": "dnc-checked-field",
                "NIJA_APOLLO_CAMPAIGN_ENABLED_FIELD_ID": "campaign-field",
            },
            clear=False,
        )

    def test_custom_dnc_evidence_is_used_when_provider_status_missing(self):
        contact = {
            "typed_custom_fields": {
                "consent-field": True,
                "consent-record-field": "consent-123",
                "legal-basis-field": "express-written-consent",
                "dnc-status-field": "Clear",
                "dnc-checked-field": "2026-10-09T01:00:00+00:00",
                "campaign-field": True,
            }
        }
        with self._field_env():
            evidence = self.feeder._evidence(contact, {})

        self.assertTrue(evidence["has_consent"])
        self.assertEqual(evidence["consent_record_id"], "consent-123")
        self.assertEqual(evidence["legal_basis"], "express-written-consent")
        self.assertTrue(evidence["dnc_clear"])
        self.assertEqual(evidence["dnc_checked_at"], "2026-10-09T01:00:00+00:00")
        self.assertTrue(evidence["explicit_campaign_enabled"])

    def test_provider_dnc_found_overrides_custom_clear(self):
        contact = {
            "typed_custom_fields": {
                "consent-field": True,
                "consent-record-field": "consent-123",
                "legal-basis-field": "express-written-consent",
                "dnc-status-field": "Clear",
                "dnc-checked-field": "2026-10-09T01:00:00+00:00",
                "campaign-field": True,
            }
        }
        with self._field_env():
            evidence = self.feeder._evidence(contact, {"dnc_status_cd": "found"})

        self.assertFalse(evidence["dnc_clear"])
        self.assertTrue(evidence["provider_dnc_found"])

    def test_missing_dnc_evidence_remains_fail_closed(self):
        contact = {
            "typed_custom_fields": {
                "consent-field": True,
                "consent-record-field": "consent-123",
                "legal-basis-field": "express-written-consent",
                "campaign-field": True,
            }
        }
        with self._field_env():
            evidence = self.feeder._evidence(contact, {})

        self.assertFalse(evidence["dnc_clear"])
        self.assertEqual(evidence["dnc_checked_at"], "")


    def test_provider_not_found_without_screening_timestamp_cannot_claim_fresh_dnc(self):
        contact = {"typed_custom_fields": {
            "consent-field": True,
            "consent-record-field": "consent-123",
            "legal-basis-field": "express-written-consent",
            "campaign-field": True,
        }}
        with self._field_env():
            with mock.patch.object(self.feeder, "_utcnow",
                                   return_value=datetime(2026, 10, 15, tzinfo=timezone.utc)):
                evidence = self.feeder._evidence(contact, {"dnc_status_cd": "not_found"})
        self.assertFalse(evidence["dnc_clear"])
        self.assertEqual(evidence["dnc_checked_at"], "")
        self.assertEqual(self.feeder._qualification_reason({
            **evidence, "suppression_clear": True, "campaign_enabled": True,
            "weekend_evidence": {"recipient_jurisdiction": "US-WA"},
        }), "dnc_not_clear")

    def test_documented_provider_screening_time_is_preserved(self):
        checked_at = "2026-10-15T00:10:00+00:00"
        with self._field_env():
            evidence = self.feeder._evidence(
                {"typed_custom_fields": {}},
                {"dnc_status_cd": "not_found", "dnc_checked_at": checked_at},
            )
        self.assertTrue(evidence["dnc_clear"])
        self.assertEqual(evidence["dnc_checked_at"], checked_at)

    def test_custom_dnc_screening_can_verify_provider_status_without_provider_timestamp(self):
        checked_at = "2026-10-15T00:10:00+00:00"
        with self._field_env():
            evidence = self.feeder._evidence(
                {"typed_custom_fields": {
                    "dnc-status-field": "Clear",
                    "dnc-checked-field": checked_at,
                }},
                {"dnc_status_cd": "not_found"},
            )
        self.assertTrue(evidence["dnc_clear"])
        self.assertEqual(evidence["dnc_checked_at"], checked_at)

    def test_conflicting_dnc_found_blocks_provider_clear(self):
        with self._field_env():
            evidence = self.feeder._evidence(
                {"typed_custom_fields": {
                    "dnc-status-field": "Found",
                    "dnc-checked-field": "2026-10-15T00:10:00+00:00",
                }},
                {"dnc_status_cd": "not_found",
                 "dnc_checked_at": "2026-10-15T00:12:00+00:00"},
            )
        self.assertFalse(evidence["dnc_clear"])
        self.assertFalse(evidence["provider_dnc_found"])

    def test_pending_provider_dnc_blocks_even_with_custom_clear(self):
        with self._field_env():
            evidence = self.feeder._evidence(
                {"typed_custom_fields": {
                    "dnc-status-field": "Clear",
                    "dnc-checked-field": "2026-10-15T00:10:00+00:00",
                }},
                {"dnc_status_cd": "pending"},
            )
        self.assertFalse(evidence["dnc_clear"])
        self.assertEqual(evidence["provider_dnc_status"], "pending")


    def test_provider_dnc_found_is_suppressed_even_when_timezone_is_missing(self):
        contact = {
            "id": "dnc-contact-without-timezone",
            "phone_numbers": [
                {"sanitized_number": "+12065550123", "dnc_status_cd": "found"}
            ],
            "typed_custom_fields": {},
        }
        with self._field_env():
            with mock.patch.object(self.feeder, "set_suppression") as suppression:
                payload, reason = self.feeder._contact_payload(contact)
        self.assertIsNone(payload)
        self.assertEqual(reason, "missing_timezone")
        suppression.assert_called_once_with(
            contact_number="+12065550123",
            reason="apollo_dnc_found",
            source="apollo",
            active=True,
        )

    def test_unverified_dnc_does_not_create_false_positive_suppression(self):
        contact = {
            "id": "pending-dnc-contact",
            "phone_numbers": [
                {"sanitized_number": "+12065550123", "dnc_status_cd": "pending"}
            ],
            "typed_custom_fields": {},
        }
        with self._field_env():
            with mock.patch.object(self.feeder, "set_suppression") as suppression:
                payload, reason = self.feeder._contact_payload(contact)
        self.assertIsNone(payload)
        self.assertEqual(reason, "missing_timezone")
        suppression.assert_not_called()


class AutodialQueueReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.autodial = importlib.import_module("render_outreach_autodial")

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {"NIJA_OUTREACH_DB_PATH": os.path.join(self.tmpdir.name, "outreach.sqlite3")},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmpdir.cleanup()

    def _base(self):
        return {
            "record_id": "apollo:contact-1",
            "contact_number": "+12065550123",
            "campaign": "NIJA Apollo Outbound",
            "call_stage": "initial",
            "contact_timezone": "America/Los_Angeles",
            "dynamic_variables": [],
            "test_mode": False,
        }

    def _ready(self):
        return {
            **self._base(),
            "has_consent": True,
            "consent_record_id": "consent-123",
            "legal_basis": "express-written-consent",
            "dnc_clear": True,
            "dnc_checked_at": datetime.now(timezone.utc).isoformat(),
            "suppression_clear": True,
            "campaign_enabled": True,
        }

    def test_unqualified_contact_is_not_active_queued(self):
        result = self.autodial.enqueue_candidate(self._base())

        self.assertFalse(result["queued"])
        self.assertEqual(result["state"], "review_required")
        self.assertIn("verified_consent_required", result["blocker"])

        with self.autodial._connect() as connection:
            row = connection.execute(
                "SELECT state, last_blocker FROM outreach_autodial_queue LIMIT 1"
            ).fetchone()
        self.assertEqual(row["state"], "review_required")
        self.assertIn("verified_consent_required", row["last_blocker"])

    def test_qualified_refresh_reactivates_same_queue_key(self):
        first = self.autodial.enqueue_candidate(self._base())
        second = self.autodial.enqueue_candidate(self._ready())

        self.assertEqual(first["queue_key"], second["queue_key"])
        self.assertTrue(second["queued"])
        self.assertEqual(second["state"], "queued")

        with self.autodial._connect() as connection:
            row = connection.execute(
                "SELECT state, last_blocker, has_consent, dnc_clear, suppression_clear, campaign_enabled "
                "FROM outreach_autodial_queue WHERE queue_key=?",
                (second["queue_key"],),
            ).fetchone()
        self.assertEqual(row["state"], "queued")
        self.assertIsNone(row["last_blocker"])
        self.assertEqual(row["has_consent"], 1)
        self.assertEqual(row["dnc_clear"], 1)
        self.assertEqual(row["suppression_clear"], 1)
        self.assertEqual(row["campaign_enabled"], 1)

    def test_startup_quarantine_parks_legacy_nonready_queue_rows(self):
        result = self.autodial.enqueue_candidate(self._base())
        with self.autodial._connect() as connection:
            connection.execute(
                "UPDATE outreach_autodial_queue SET state='queued', last_blocker=NULL WHERE queue_key=?",
                (result["queue_key"],),
            )
            connection.commit()

        changed = self.autodial._quarantine_static_nonready()
        self.assertEqual(changed, 1)

        with self.autodial._connect() as connection:
            row = connection.execute(
                "SELECT state, last_blocker FROM outreach_autodial_queue WHERE queue_key=?",
                (result["queue_key"],),
            ).fetchone()
        self.assertEqual(row["state"], "review_required")
        self.assertEqual(row["last_blocker"], "verified_consent_required")


if __name__ == "__main__":
    unittest.main()
