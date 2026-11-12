"""Synthetic provider contract tests, with no credentials or network calls."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
import unittest
from unittest.mock import patch

from website_profit_sources import PRODUCTION_HOSTS, collect_ga4, collect_stripe
from scripts.collect_website_profit_sources import main, _NoRedirect

WINDOW = dict(start="2026-10-01", end="2026-10-31", reporting_timezone="America/Los_Angeles")


class SourceCollectionTests(unittest.TestCase):
    def setUp(self):
        self.ga4 = {
            "metadata": {"timeZone": WINDOW["reporting_timezone"]},
            "metricHeaders": [{"name": "totalUsers", "type": "TYPE_INTEGER"}],
            "rows": [{"metricValues": [{"value": "181"}]}], "rowCount": 1,
        }
        self.transaction = {
            "id": "txn_fixture1", "created": int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp()),
            "amount": 9900, "fee": 317, "net": 9583, "currency": "usd",
            "source": "ch_fixture", "type": "charge", "reporting_category": "charge",
            "description": "PRIVATE DESCRIPTION", "email": "PRIVATE EMAIL",
        }

    def ga(self, response=None):
        return collect_ga4(lambda *_: deepcopy(self.ga4 if response is None else response), property_id="123", **WINDOW)

    def stripe(self, pages, **kwargs):
        calls = []

        def get(path, query):
            calls.append((path, dict(query)))
            return {"id": "acct_fixture"} if path == "/v1/account" else pages.pop(0)

        result = collect_stripe(get, expected_account_id="acct_fixture", **WINDOW, **kwargs)
        return result, calls

    def page(self, *items, more=False):
        return {"object": "list", "data": list(items), "has_more": more}

    def test_ga4_requests_ungrouped_production_total(self):
        calls = []
        def report(path, body):
            calls.append((path, body))
            return self.ga4
        result = collect_ga4(report, property_id="123", **WINDOW)
        body = calls[0][1]
        self.assertNotIn("dimensions", body)
        self.assertEqual(body["metrics"], [{"name": "totalUsers"}])
        self.assertEqual(body["dimensionFilter"]["filter"]["inListFilter"]["values"], list(PRODUCTION_HOSTS))
        self.assertFalse(any("preview" in h for h in PRODUCTION_HOSTS))
        self.assertEqual(result["observed_total_users"], 181)
        self.assertFalse(result["visitor_counts_verified"])

    def test_ga4_does_not_sum_grouped_or_partial_rows(self):
        for changes in ({"dimensionHeaders": [{"name": "hostName"}]}, {"rowCount": 2},
                        {"metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.ga({**self.ga4, **changes})

    def test_ga4_requires_matching_timezone_and_quality(self):
        for metadata in ({}, {"timeZone": "UTC"},
                         {"timeZone": WINDOW["reporting_timezone"], "subjectToThresholding": True},
                         {"timeZone": WINDOW["reporting_timezone"], "dataLossFromOtherRow": True},
                         {"timeZone": WINDOW["reporting_timezone"], "samplingMetadatas": [{}]}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.ga({**self.ga4, "metadata": metadata})

    def test_ga4_zero_is_observation_only(self):
        result = self.ga({**self.ga4, "rows": [], "rowCount": 0})
        self.assertEqual(result["observed_total_users"], 0)
        self.assertFalse(result["visitor_counts_verified"])

    def test_ga4_rejects_malformed_values(self):
        for value in ("-1", "1.1", "NaN", None, 181):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.ga({**self.ga4, "rows": [{"metricValues": [{"value": value}]}]})

    def test_stripe_paginates_and_removes_private_fields(self):
        other = {**self.transaction, "id": "txn_fixture2", "type": "payout", "reporting_category": "payout"}
        result, calls = self.stripe([self.page(self.transaction, more=True), self.page(other)])
        self.assertEqual(len(result["transactions"]), 2)
        self.assertEqual(calls[2][1]["starting_after"], "txn_fixture1")
        self.assertNotIn("currency", calls[1][1])
        self.assertNotIn("type", calls[1][1])
        self.assertNotIn("PRIVATE", repr(result))
        self.assertIsNone(result["net_profit_per_visitor_usd"])
        self.assertFalse(result["revenue_complete"])
        self.assertFalse(result["livemode_verified"])

    def test_stripe_empty_is_not_certified_zero_revenue(self):
        result, _ = self.stripe([self.page()])
        self.assertEqual(result["transactions"], [])
        self.assertTrue(result["pagination_complete"])
        self.assertFalse(result["provider_revenue_verified"])
        self.assertIsNone(result["net_profit_usd"])

    def test_stripe_identity_mismatch_stops_before_transactions(self):
        calls = []
        def wrong(path, query):
            calls.append(path)
            return {"id": "acct_wrong"}
        with self.assertRaises(ValueError):
            collect_stripe(wrong, expected_account_id="acct_fixture", **WINDOW)
        self.assertEqual(calls, ["/v1/account"])

    def test_stripe_rejects_repeated_and_incomplete_pages(self):
        for pages in ([self.page(more=True)], [self.page(self.transaction, more=True), self.page(self.transaction)],
                      [{"object": "list", "data": [], "has_more": "false"}]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                self.stripe(deepcopy(pages))
        with self.assertRaises(ValueError):
            self.stripe([self.page(self.transaction, more=True)], max_pages=1)

    def test_stripe_rejects_bad_amounts_timestamps_and_expanded_sources(self):
        for change in ({"amount": True}, {"amount": 99.0}, {"net": 1}, {"created": 0},
                       {"currency": "USD"}, {"source": {"email": "PRIVATE"}}, {"type": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.stripe([self.page({**self.transaction, **change})])

    def test_window_uses_local_midnights_across_daylight_saving(self):
        result, calls = self.stripe([self.page()])
        query = calls[1][1]
        self.assertEqual(query["created[gte]"], int(datetime(2026, 10, 1, 7, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(query["created[lt]"], int(datetime(2026, 11, 1, 7, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(result["timezone"], WINDOW["reporting_timezone"])

    def test_invalid_windows_never_call_provider(self):
        for window in ({**WINDOW, "start": "2026-11-01"}, {**WINDOW, "end": "9999-01-01"}):
            with self.subTest(window=window), self.assertRaises(ValueError):
                collect_ga4(lambda *_: self.fail("provider called"), property_id="123", **window)

    def test_transport_errors_do_not_become_empty_data(self):
        def fail(*_):
            raise ConnectionError("provider unavailable")
        with self.assertRaises(ConnectionError):
            collect_ga4(fail, property_id="123", **WINDOW)
        with self.assertRaises(ConnectionError):
            collect_stripe(fail, expected_account_id="acct_fixture", **WINDOW)

    def test_cli_fails_without_secure_credentials_and_prints_no_candidate(self):
        output, errors = io.StringIO(), io.StringIO()
        argv = ["--property-id", "123", "--account-id", "acct_fixture", "--start", WINDOW["start"],
                "--end", WINDOW["end"], "--timezone", WINDOW["reporting_timezone"]]
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(argv), 2)
        self.assertEqual(output.getvalue(), "")

    def test_cli_uses_only_provider_reads_and_emits_unsigned_provisional_data(self):
        argv = ["--property-id", "123", "--account-id", "acct_fixture", "--start", WINDOW["start"],
                "--end", WINDOW["end"], "--timezone", WINDOW["reporting_timezone"]]
        env = {"NIJA_PROFIT_GA4_ACCESS_TOKEN": "synthetic-only", "NIJA_PROFIT_STRIPE_READ_KEY": "rk_live_" + "fixture"}
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), redirect_stdout(output), patch(
            "scripts.collect_website_profit_sources._request",
            side_effect=[self.ga4, {"id": "acct_fixture"}, self.page()],
        ) as request:
            self.assertEqual(main(argv), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["verification_status"], "PROVISIONAL")
        self.assertNotIn("signature", result)
        self.assertIsNone(result["net_profit_per_visitor_usd"])
        self.assertEqual(len(request.call_args_list), 3)
        self.assertEqual(len(request.call_args_list[0].args), 3)  # read-only GA4 POST report
        self.assertTrue(all(len(call.args) == 2 for call in request.call_args_list[1:]))  # Stripe GETs
        self.assertNotIn("synthetic-only", output.getvalue())

    def test_cli_provider_failure_leaks_neither_partial_data_nor_error_body(self):
        argv = ["--property-id", "123", "--account-id", "acct_fixture", "--start", WINDOW["start"],
                "--end", WINDOW["end"], "--timezone", WINDOW["reporting_timezone"]]
        env = {"NIJA_PROFIT_GA4_ACCESS_TOKEN": "synthetic-only", "NIJA_PROFIT_STRIPE_READ_KEY": "rk_live_" + "fixture"}
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env, clear=True), redirect_stdout(output), redirect_stderr(errors), patch(
            "scripts.collect_website_profit_sources._request", side_effect=[self.ga4, ValueError("PRIVATE")],
        ):
            self.assertEqual(main(argv), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("PRIVATE", errors.getvalue())

    def test_credentials_never_follow_redirects(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.com"))
