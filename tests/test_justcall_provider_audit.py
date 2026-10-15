"""Read-only JustCall provider-history reconciliation regression tests."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit
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

    def test_current_day_does_not_query_future_end_date(self):
        paths = []
        def respond(method, path):
            self.assertEqual(method, "GET")
            paths.append(path)
            return {"data": []}
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertTrue(result["verified"])
        self.assertEqual(len(paths), 2)
        for path in paths:
            query = parse_qs(urlsplit(path).query)
            self.assertEqual(query["from_datetime"], ["2026-10-07"])
            self.assertNotIn("to_datetime", query)

    def test_historical_day_uses_nonfuture_end_date(self):
        later = datetime(2026, 10, 21, tzinfo=timezone.utc)
        paths = []
        with mock.patch.object(
            audit, "_provider_request",
            side_effect=lambda method, path: (paths.append(path) or {"data": []}),
        ):
            audit._history_for_source("justcall", "/calls", date(2026, 10, 9), later)
        q = parse_qs(urlsplit(paths[0]).query)
        self.assertEqual(q["from_datetime"], ["2026-10-07"])
        self.assertEqual(q["to_datetime"], ["2026-10-11"])

    def test_400_falls_back_once_to_documented_minimal_readonly_filters(self):
        seen = []
        def respond(method, path):
            self.assertEqual(method, "GET")
            seen.append(path)
            query = parse_qs(urlsplit(path).query)
            if path.startswith("/sales_dialer/calls"):
                return {"data": []}
            if "sort" in query:
                raise OutreachProviderError("bad request", status_code=400)
            self.assertNotIn("call_direction", query)
            self.assertNotIn("to_datetime", query)
            self.assertEqual(query["from_datetime"], ["2026-10-07"])
            return {"data": [row(9)]}
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertTrue(result["verified"])
        self.assertEqual(result["confirmed_outbound_attempts"], 1)
        self.assertEqual(result["sources"]["justcall"]["query_mode"], "compat")
        self.assertEqual(len(seen), 3)

    def test_fallback_400_stays_unverified_not_zero(self):
        with mock.patch.object(
            audit, "_provider_request",
            side_effect=OutreachProviderError("bad request", status_code=400),
        ):
            result = audit.audit_provider_today(NOW)
        self.assertFalse(result["verified"])
        self.assertEqual(result["blocked_source"], "justcall")
        self.assertEqual(result["reason"], "provider_api_error_http_400")
        self.assertIsNone(result["confirmed_outbound_attempts"])
        self.assertIsNone(result["gap_to_target"])

    def test_400_after_partial_pagination_restarts_from_first_page(self):
        seen = []
        def respond(method, path):
            q = parse_qs(urlsplit(path).query)
            seen.append((q["page"][0], "sort" in q))
            if path.startswith("/sales_dialer/calls"):
                return {"data": []}
            if "sort" in q and q["page"] == ["1"]:
                raise OutreachProviderError("bad request", status_code=400)
            if "sort" in q:
                return {"data": [row(i) for i in range(100)]}
            return {"data": [row(101)]}
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertTrue(result["verified"])
        self.assertEqual(result["confirmed_outbound_attempts"], 1)
        self.assertEqual(result["sources"]["justcall"]["query_mode"], "compat")
        self.assertEqual(seen[:3], [("0", True), ("1", True), ("0", False)])

    def test_sales_dialer_requires_explicit_outbound_direction(self):
        undirected = row(7, source="sales_dialer")
        del undirected["call_info"]["direction"]
        def respond(method, path):
            if path.startswith("/calls?"):
                return {"data": []}
            return {"data": [undirected]}
        with mock.patch.object(audit, "_provider_request", side_effect=respond):
            result = audit.audit_provider_today(NOW)
        self.assertFalse(result["verified"])
        self.assertEqual(result["blocked_source"], "sales_dialer")
        self.assertEqual(result["reason"], "call_direction_unverified")
        self.assertIsNone(result["confirmed_outbound_attempts"])

    def test_inbound_sales_dialer_record_is_not_outbound(self):
        incoming = row(7, source="sales_dialer")
        incoming["call_info"]["direction"] = "Incoming"
        with mock.patch.object(audit, "_provider_request", side_effect=[
            {"data": []}, {"data": [incoming]}
        ]):
            result = audit.audit_provider_today(NOW)
        self.assertTrue(result["verified"])
        self.assertEqual(result["confirmed_outbound_attempts"], 0)
        self.assertEqual(result["sources"]["sales_dialer"]["excluded"], 1)

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
