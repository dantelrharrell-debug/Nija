"""NIJA seven-day outbound calling guard regression tests.

No test places a real call or accesses JustCall credentials.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import render_outreach_autodial as dial
import render_outreach_routes as routes

SECRET = "test-nija-weekend-clearance-key-only-" * 2


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def evidence(number="+12065550123", state="US-WA", local_day="2026-10-11",
             campaign="NIJA Apollo Outbound", consent_id="consent-123",
             checked="2026-10-11T15:59:00Z", recipient_timezone="America/Los_Angeles",
             approved=True):
    obj = {
        "approved": approved,
        "recipient_jurisdiction": state,
        "recipient_timezone": recipient_timezone,
        "clearance_id": "legal-review-123",
        "cleared_local_date": local_day,
        "checked_at": checked,
    }
    fields = {
        "phone_digits": dial.phone_key(number),
        "campaign": campaign,
        "consent_record_id": consent_id,
        "jurisdiction": state,
        "timezone": recipient_timezone,
        "clearance_id": obj["clearance_id"],
        "local_date": local_day,
        "checked_at": checked,
    }
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    obj["signature"] = hmac.new(
        SECRET.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return obj


class WeekendRulesTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "NIJA_JUSTCALL_WEEKEND_CLEARANCE_SECRET": SECRET,
            "NIJA_AUTODIAL_WEEKDAYS_ONLY": "0",
            "NIJA_AUTODIAL_LOCAL_START_HOUR": "9",
            "NIJA_AUTODIAL_LOCAL_END_HOUR": "20",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def decide(self, details, now="2026-10-11T16:00:00Z", number="+12065550123",
               campaign="NIJA Apollo Outbound", consent_id="consent-123"):
        return dial._weekend_call_eligibility(
            json.dumps(details), utc(now),
            number=number, campaign=campaign, consent_record_id=consent_id,
        )

    def test_verified_sunday_clearance_allows_permitted_jurisdiction(self):
        self.assertEqual(self.decide(evidence()), (True, "ok"))

    def test_sunday_without_clearance_is_blocked(self):
        self.assertEqual(
            self.decide(evidence(approved=False)),
            (False, "weekend_clearance_required"),
        )

    def test_missing_jurisdiction_fails_on_weekdays_too(self):
        allowed, reason = self.decide({}, now="2026-10-09T16:00:00Z")
        self.assertFalse(allowed)
        self.assertEqual(reason, "recipient_jurisdiction_required")

    def test_sunday_bans_apply_even_with_approval(self):
        for state in ("US-PA", "US-AL", "US-MS"):
            with self.subTest(state=state):
                allowed, reason = self.decide(evidence(state=state))
                self.assertFalse(allowed)
                self.assertEqual(reason, "jurisdiction_sunday_prohibited")

    def test_wrong_date_or_number_cannot_reuse_signed_clearance(self):
        self.assertEqual(self.decide(evidence(local_day="2026-10-10"))[1],
                         "weekend_clearance_date_required")
        self.assertEqual(self.decide(evidence(), number="+12065550999")[1],
                         "weekend_clearance_signature_invalid")

    def test_changed_campaign_or_consent_blocks_replay(self):
        self.assertEqual(self.decide(evidence(), campaign="Other")[1],
                         "weekend_clearance_signature_invalid")
        self.assertEqual(self.decide(evidence(), consent_id="other")[1],
                         "weekend_clearance_signature_invalid")

    def test_expired_and_forged_clearance_blocked(self):
        forged = evidence()
        forged["signature"] = "0" * 64
        self.assertEqual(self.decide(forged)[1],
                         "weekend_clearance_signature_invalid")
        changed_timezone = evidence()
        changed_timezone["recipient_timezone"] = "America/New_York"
        self.assertEqual(self.decide(changed_timezone)[1],
                         "weekend_clearance_signature_invalid")
        old = evidence(checked="2026-10-09T16:00:00Z")
        self.assertEqual(self.decide(old)[1], "weekend_clearance_expired")

    def test_missing_signing_secret_fails_closed(self):
        with mock.patch.dict(os.environ, {"NIJA_JUSTCALL_WEEKEND_CLEARANCE_SECRET": ""}):
            self.assertEqual(self.decide(evidence())[1],
                             "weekend_clearance_signature_invalid")

    def test_pennsylvania_evening_ban_from_effective_date(self):
        # Monday October 19 2026, 19:30 America/New_York.
        local = utc("2026-10-19T23:30:00Z")
        allowed, reason = dial._weekend_call_eligibility(
            json.dumps(evidence(
                number="+12155550100",
                state="US-PA",
                local_day="2026-10-19",
                checked="2026-10-19T23:29:00Z",
                recipient_timezone="America/New_York",
            )),
            local,
            number="+12155550100", campaign="NIJA Apollo Outbound",
            consent_record_id="consent-123",
        )
        self.assertEqual((allowed, reason), (False, "jurisdiction_hours_prohibited"))


class QueueAndDirectRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.dict(os.environ, {
            "NIJA_OUTREACH_DB_PATH": str(Path(self.tmp.name) / "outreach.sqlite3"),
            "NIJA_AUTODIAL_WEEKDAYS_ONLY": "0",
            "NIJA_JUSTCALL_WEEKEND_CLEARANCE_SECRET": SECRET,
            "NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF": "1",
            "NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED": "0",
        })
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def row(self):
        now = utc("2026-10-11T16:00:00Z")
        return {
            "has_consent": 1,
            "consent_record_id": "consent-123",
            "legal_basis": "express-written-consent",
            "dnc_clear": 1,
            "dnc_checked_at": now.isoformat(),
            "suppression_clear": 1,
            "contact_number": "+12065550123",
            "contact_timezone": "America/Los_Angeles",
            "campaign_enabled": 1,
            "campaign": "NIJA Apollo Outbound",
            "weekend_evidence_json": json.dumps(evidence()),
        }

    def test_human_handoff_gate_applies_even_if_everything_else_is_ready(self):
        with (
            mock.patch.object(dial, "_quota_snapshot", return_value={
                "weekday_open": True, "remaining": 300,
            }),
            mock.patch.object(dial, "_active_call_exists", return_value=False),
            mock.patch.object(dial, "is_suppressed", return_value=False),
        ):
            blockers, _ = dial._eligibility(self.row(), utc("2026-10-11T16:00:00Z"))
            self.assertIn("human_handoff_not_verified", blockers)
            with mock.patch.dict(os.environ, {"NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED": "1"}):
                blockers, _ = dial._eligibility(self.row(), utc("2026-10-11T16:00:00Z"))
                self.assertEqual(blockers, [])

    def test_signed_recipient_timezone_overrides_contact_timezone(self):
        row = self.row()
        row["contact_timezone"] = "America/Los_Angeles"
        row["weekend_evidence_json"] = json.dumps(evidence(
            state="US-PA",
            local_day="2026-10-19",
            checked="2026-10-19T23:29:00Z",
            recipient_timezone="America/New_York",
        ))
        with (
            mock.patch.object(dial, "_quota_snapshot", return_value={
                "weekday_open": True, "remaining": 300,
            }),
            mock.patch.object(dial, "_active_call_exists", return_value=False),
            mock.patch.object(dial, "is_suppressed", return_value=False),
            mock.patch.dict(os.environ, {"NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED": "1"}),
        ):
            blockers, _ = dial._eligibility(row, utc("2026-10-19T23:30:00Z"))
        self.assertIn("jurisdiction_hours_prohibited", blockers)

    def test_existing_database_migrates_without_dropping_rows(self):
        with sqlite3.connect(os.environ["NIJA_OUTREACH_DB_PATH"]) as con:
            con.execute(
                "CREATE TABLE outreach_autodial_queue ("
                "id INTEGER PRIMARY KEY, state TEXT, next_attempt_at TEXT, "
                "phone_key TEXT, updated_at TEXT)"
            )
        with dial._connect() as con:
            dial._ensure_schema(con)
            names = {
                item["name"] for item in con.execute(
                    "PRAGMA table_info(outreach_autodial_queue)"
                )
            }
        self.assertIn("weekend_evidence_json", names)

    def test_daily_quota_paces_attempts_instead_of_bursting(self):
        start = utc("2026-10-11T16:00:00Z")
        with mock.patch.dict(os.environ, {
            "NIJA_AUTODIAL_DAILY_CAP": "300",
            "NIJA_AUTODIAL_MIN_SUBMISSION_INTERVAL_SECONDS": "120",
        }):
            accepted, key, reason = dial._reserve_quota(start)
            self.assertEqual((accepted, reason), (True, "ok"))
            accepted, _, reason = dial._reserve_quota(start.replace(second=30))
            self.assertEqual((accepted, reason), (False, "pacing_interval_not_elapsed"))
            snap = dial._quota_snapshot(start.replace(second=30))
            self.assertEqual(snap["used"], 1)
            self.assertEqual(snap["remaining"], 299)
            self.assertFalse(snap["pacing_ready"])
            accepted, _, reason = dial._reserve_quota(utc("2026-10-11T16:02:01Z"))
            self.assertEqual((accepted, reason), (True, "ok"))
            self.assertEqual(dial._quota_snapshot(utc("2026-10-11T16:02:01Z"))["used"], 2)

    def test_ready_queue_persists_signed_weekend_evidence(self):
        now = utc("2026-10-11T16:00:00Z")
        valid = evidence()
        payload = {
            "record_id": "apollo:contact-1",
            "contact_number": "+12065550123",
            "campaign": "NIJA Apollo Outbound",
            "call_stage": "initial",
            "contact_timezone": "America/Los_Angeles",
            "has_consent": True,
            "consent_record_id": "consent-123",
            "legal_basis": "express-written-consent",
            "dnc_clear": True,
            "dnc_checked_at": now.isoformat(),
            "suppression_clear": True,
            "campaign_enabled": True,
            "weekend_evidence": valid,
        }
        result = dial.enqueue_candidate(payload)
        self.assertTrue(result["queued"])
        with dial._connect() as con:
            stored = con.execute(
                "SELECT weekend_evidence_json FROM outreach_autodial_queue WHERE queue_key=?",
                (result["queue_key"],),
            ).fetchone()
        decoded = json.loads(stored["weekend_evidence_json"])
        self.assertEqual(decoded["signature"], valid["signature"])
        self.assertEqual(decoded["recipient_jurisdiction"], "US-WA")
        self.assertEqual(decoded["recipient_timezone"], "America/Los_Angeles")

    def test_legacy_stdlib_route_cannot_dial_provider(self):
        handler = type("Request", (), {"path": "/api/justcall/calls"})()
        with (
            mock.patch.object(routes, "_service_authorized",
                              return_value=(True, 200, "ok")),
            mock.patch.object(routes, "_send_json") as send,
            mock.patch.object(routes, "_provider_request") as provider,
        ):
            self.assertTrue(routes.handle_outreach_post(handler))
            self.assertEqual(send.call_args.args[1], 409)
            provider.assert_not_called()

    def test_legacy_flask_route_cannot_dial_provider(self):
        try:
            from flask import Flask
            from justcall_api import justcall_api
        except ImportError:
            self.skipTest("Flask unavailable in this environment")
        app = Flask(__name__)
        app.register_blueprint(justcall_api)
        with mock.patch.dict(os.environ, {"NIJA_OUTREACH_SERVICE_TOKEN": "test-token"}):
            response = app.test_client().post(
                "/api/justcall/calls",
                json={"contact_number": "+12065550123", "has_consent": True},
                headers={"X-NIJA-Outreach-Token": "test-token"},
            )
        self.assertEqual(response.status_code, 409)


class ApolloJurisdictionTests(unittest.TestCase):
    def test_feeder_requires_explicit_verified_recipient_jurisdiction(self):
        import render_apollo_feeder as feeder

        fields = {
            "NIJA_APOLLO_RECIPIENT_JURISDICTION_FIELD_ID": "recipient-state",
            "NIJA_APOLLO_WEEKEND_APPROVED_FIELD_ID": "weekend-approval",
            "NIJA_APOLLO_WEEKEND_CLEARANCE_ID_FIELD_ID": "weekend-id",
            "NIJA_APOLLO_WEEKEND_LOCAL_DATE_FIELD_ID": "weekend-date",
            "NIJA_APOLLO_WEEKEND_CHECKED_AT_FIELD_ID": "weekend-time",
            "NIJA_APOLLO_WEEKEND_SIGNATURE_FIELD_ID": "weekend-signature",
            "NIJA_APOLLO_RECIPIENT_TIMEZONE_FIELD_ID": "recipient-timezone",
        }
        contact = {
            "person_location_state": "Pennsylvania",  # must NOT be inferred
            "organization_name": "Pennsylvania Example",
            "typed_custom_fields": {
                "recipient-state": "US-WA",
                "weekend-approval": True,
                "weekend-id": "legal-review-123",
                "weekend-date": "2026-10-11",
                "weekend-time": "2026-10-11T15:59:00Z",
                "weekend-signature": "signed-evidence",
                "recipient-timezone": "America/Los_Angeles",
            },
        }
        with mock.patch.dict(os.environ, fields):
            obj = feeder._jurisdiction_evidence(contact)
            self.assertEqual(obj["recipient_jurisdiction"], "US-WA")
            self.assertEqual(obj["recipient_timezone"], "America/Los_Angeles")
            self.assertEqual(obj["signature"], "signed-evidence")
            self.assertTrue(obj["approved"])
            contact["typed_custom_fields"].pop("recipient-state")
            self.assertEqual(
                feeder._jurisdiction_evidence(contact)["recipient_jurisdiction"], ""
            )

    def test_feeder_cannot_call_without_jurisdiction_or_consent(self):
        import render_apollo_feeder as feeder

        ready = {
            "has_consent": True,
            "consent_record_id": "consent-123",
            "legal_basis": "express-written-consent",
            "dnc_clear": True,
            "suppression_clear": True,
            "campaign_enabled": True,
            "weekend_evidence": {},
        }
        self.assertEqual(
            feeder._qualification_reason(ready), "recipient_jurisdiction_required"
        )
        ready["weekend_evidence"] = {"recipient_jurisdiction": "US-WA"}
        self.assertEqual(feeder._qualification_reason(ready), "call_ready")
        ready["has_consent"] = False
        self.assertEqual(feeder._qualification_reason(ready), "consent_required")


if __name__ == "__main__":
    unittest.main()
