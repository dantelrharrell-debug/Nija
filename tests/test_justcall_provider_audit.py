"""Read-only JustCall provider-history reconciliation regression tests."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

import render_justcall_provider_audit as audit
from render_outreach_routes import OutreachProviderError

NOW = datetime(2026, 10, 10, 4, 0, tzinfo=timezone.utc)  # Oct 9, 9pm Pacific


def row(i, utc_day="2026-10-09", clock="17:00:00", source="justcall"):
    return {
        "id" if source == "justcall" else "call_id": i,
        "call_sid": f"call_{i}",
        "call_date": utc_day,
        "call_time": clock,
        "call_info": {"direction": "Outgoing", "type": "Unanswered"},
    }


class ProviderAuditTests(unittest.TestCase):
    def test_provider_verified_both_sources_and_deduplicated(self):
        def respond(method, path):
            if path.startswith("/calls?"):
                return {"data": [row(1), row(2)]}
            return {"data": [row(2, source="sales_dialer"), row(3, source="sales_dialer")]}
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertTrue(result["verified"])
        self.assertEqual(result["confirmed_outbound_attempts"], 3)
        self.assertEqual(result["gap_to_target"], 297)

    def test_never_counts_a_partial_provider_failure_as_verified(self):
        def respond(method, path):
            if path.startswith("/calls?"):
                return {"data": [row(1)]}
            raise OutreachProviderError("forbidden", status_code=403)
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertFalse(result["verified"])
        self.assertIsNone(result["confirmed_outbound_attempts"])
        self.assertEqual(result["blocked_source"], "sales_dialer")

    def test_los_angeles_day_boundary_not_utc_calendar_day(self):
        def respond(method, path):
            if path.startswith("/calls?"):
                return {"data": [row(1, "2026-10-10", "04:00:00"),
                                 row(2, "2026-10-10", "08:00:00")]}
            return {"data": []}
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertTrue(result["verified"])
        self.assertEqual(result["confirmed_outbound_attempts"], 1)

    def test_blocked_and_cancelled_calls_do_not_count(self):
        excluded = [row(1), row(2), row(3)]
        excluded[0]["call_info"]["type"] = "Outgoing blocked call"
        excluded[1]["call_info"]["type"] = "Outgoing cancelled call"
        with mock.patch.object(audit, "_provider_request", side_effect=[
            {"data": excluded}, {"data": []}
        ]):
            result = audit.audit_provider_today(NOW)
        self.assertEqual(result["confirmed_outbound_attempts"], 1)

    def test_missing_timestamp_is_unverified_not_zero(self):
        bad = row(1)
        del bad["call_time"]
        with mock.patch.object(audit, "_provider_request", return_value={"data": [bad]}):
            result = audit.audit_provider_today(NOW)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "call_utc_timestamp_invalid")
        self.assertIsNone(result["confirmed_outbound_attempts"])

    def test_provider_pagination_does_not_duplicate_calls(self):
        page_calls = [row(i) for i in range(100)]
        def respond(method, path):
            if path.startswith("/sales_dialer/"):
                return {"data": []}
            if "page=0" in path:
                return {"data": page_calls, "total_count": 101}
            return {"data": [row(101)], "total_count": 101}
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertTrue(result["verified"])
        self.assertEqual(result["confirmed_outbound_attempts"], 101)


if __name__ == "__main__":
    unittest.main()
