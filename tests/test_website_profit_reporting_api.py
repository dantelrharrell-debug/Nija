"""Security and financial-integrity tests for the read-only website profit API."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from website_net_profit import COST_CATEGORIES
from website_revenue_attribution import REVENUE_SOURCES
from website_profit_reporting_api import create_profit_blueprint, sign_evidence


class WebsiteProfitApiTests(unittest.TestCase):
    token = "read-only-" + "t" * 48
    key = "evidence-" + "k" * 48
    period = "2025-04"

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        config = {
            "NIJA_PROFIT_DASHBOARD_TOKEN": self.token,
            "NIJA_PROFIT_EVIDENCE_HMAC_KEY": self.key,
            "NIJA_PROFIT_EVIDENCE_DIR": self.tempdir.name,
        }
        env = patch.dict(os.environ, config)
        env.start()
        self.addCleanup(env.stop)
        app = Flask(__name__)
        app.register_blueprint(create_profit_blueprint())
        app.testing = True
        self.client = app.test_client()

    def request(self, *, period="2025-04", token=None):
        headers = {"Authorization": "Bearer " + (self.token if token is None else token)}
        return self.client.get("/api/admin/website-profit", query_string={"period": period}, headers=headers)

    def evidence(self, period=None, *, certify=True):
        period = period or self.period
        events = [
            {"type": "visit", "event_id": "v-1", "visitor_id": "visitor-1", "period": period},
            {"type": "visit", "event_id": "v-2", "visitor_id": "visitor-2", "period": period},
            {
                "type": "qualified_lead", "event_id": "l-1", "lead_id": "lead-1",
                "visitor_id": "visitor-1", "period": period,
            },
            {
                "type": "revenue", "event_id": "stripe-1", "source": "stripe",
                "verified": True, "amount_usd": "12.00", "period": period,
            },
            {
                "type": "refund", "event_id": "stripe-refund-1", "source": "stripe",
                "verified": True, "amount_usd": "2.00", "period": period,
            },
        ]
        costs = [
            {"event_id": "hosting-1", "category": "hosting", "verified": True, "amount_usd": "4.00", "period": period},
        ]
        body = {
            "reporting_period": period,
            "revenue_events": events,
            "cost_events": costs,
            "revenue_complete": certify,
            "costs_complete": certify,
            "certification": {
                "visitor_counts_verified": certify,
                "analytics_consent_verified": certify,
                "provider_revenue_verified": certify,
                "all_costs_verified": certify,
                "qualified_leads_verified": certify,
            },
            "reconciliation": {
                "accounting_basis": "cash",
                "bank_reconciled": certify,
                "revenue_sources": {source: certify for source in REVENUE_SOURCES},
                "cost_categories": {category: certify for category in COST_CATEGORIES},
            },
            "reconciled_at": "2025-05-01T00:00:00Z",
        }
        self.save_evidence(body)
        return body

    def save_evidence(self, body):
        body["signature"] = sign_evidence(body, self.key)
        Path(self.tempdir.name, body["reporting_period"] + ".json").write_text(
            json.dumps(body), encoding="utf-8"
        )

    def test_signed_closed_month_returns_aggregate_only(self):
        self.evidence()
        response = self.request()
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "verified")
        self.assertEqual(data["unique_visitors"], 2)
        self.assertEqual(data["unique_qualified_leads"], 1)
        self.assertEqual(data["net_profit_usd"], "6.00")
        self.assertEqual(data["net_profit_per_visitor_usd"], "3.00")
        self.assertEqual(data["net_profit_per_qualified_lead_usd"], "6.00")
        self.assertIs(data["visitor_target_met"], True)
        self.assertNotIn("visitor-1", response.get_data(as_text=True))
        self.assertEqual(response.headers["Cache-Control"], "no-store, private")

    def test_rejects_unknown_token(self):
        self.evidence()
        response = self.request(token="wrong")
        self.assertEqual(response.status_code, 401)

    def test_rejects_no_authorization(self):
        self.evidence()
        response = self.client.get("/api/admin/website-profit?period=2025-04")
        self.assertEqual(response.status_code, 401)

    def test_requires_configuration(self):
        with patch.dict(os.environ, {"NIJA_PROFIT_EVIDENCE_HMAC_KEY": ""}):
            response = self.request()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "unavailable")

    def test_missing_evidence_is_not_a_zero_profit_claim(self):
        response = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "unverified")
        self.assertEqual(response.get_json()["verification_status"], "UNVERIFIED")
        self.assertIsNone(response.get_json()["unique_visitors"])
        self.assertIsNone(response.get_json()["gross_collected_revenue_usd"])
        self.assertIsNone(response.get_json()["verified_costs_usd"])
        self.assertIsNone(response.get_json()["net_profit_usd"])

    def test_unverified_analytics_are_not_returned_as_a_visitor_count(self):
        record = self.evidence()
        record["certification"]["visitor_counts_verified"] = False
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        data = self.request().get_json()
        self.assertIsNone(data["unique_visitors"])
        self.assertIsNone(data["net_profit_per_visitor_usd"])
        self.assertEqual(data["visitor_count_source"], "unverified")
        self.assertEqual(data["verification_status"], "UNVERIFIED")

    def test_visitor_counts_require_separate_analytics_consent_certification(self):
        record = self.evidence()
        del record["certification"]["analytics_consent_verified"]
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        data = self.request().get_json()
        self.assertIsNone(data["unique_visitors"])
        self.assertIsNone(data["net_profit_per_visitor_usd"])
        self.assertEqual(data["visitor_count_source"], "unverified")
        self.assertFalse(data["source_status"]["analytics_consent_verified"])
        self.assertEqual(data["verification_status"], "UNVERIFIED")

    def test_zero_verified_visitors_do_not_produce_a_profit_ratio(self):
        record = self.evidence()
        record["revenue_events"] = [
            event for event in record["revenue_events"]
            if event["type"] not in {"visit", "qualified_lead"}
        ]
        record["aggregate_counts"] = {"unique_visitors": 0, "unique_qualified_leads": 0}
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        data = self.request().get_json()
        self.assertEqual(data["unique_visitors"], 0)
        self.assertIsNone(data["net_profit_usd"])
        self.assertIsNone(data["net_profit_per_visitor_usd"])
        self.assertIsNone(data["visitor_target_met"])
        self.assertEqual(data["verification_status"], "UNVERIFIED")

    def test_evidence_from_another_environment_is_not_visible(self):
        self.evidence()
        other_environment = tempfile.TemporaryDirectory()
        self.addCleanup(other_environment.cleanup)
        with patch.dict(os.environ, {"NIJA_PROFIT_EVIDENCE_DIR": other_environment.name}):
            data = self.request().get_json()
        self.assertEqual(data["verification_status"], "UNVERIFIED")
        self.assertIsNone(data["net_profit_usd"])

    def test_provider_outage_or_partial_close_keeps_totals_unknown(self):
        record = self.evidence(certify=False)
        record["certification"]["visitor_counts_verified"] = True
        record["certification"]["analytics_consent_verified"] = True
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        data = self.request().get_json()
        self.assertEqual(data["verification_status"], "PARTIAL")
        self.assertIsNone(data["gross_collected_revenue_usd"])
        self.assertIsNone(data["refunds_usd"])
        self.assertIsNone(data["verified_costs_usd"])
        self.assertIsNone(data["net_profit_usd"])

    def test_cannot_forge_revenue_after_signing(self):
        evidence = self.evidence()
        evidence["revenue_events"][3]["amount_usd"] = "9999.00"
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(evidence), encoding="utf-8")
        response = self.request()
        self.assertEqual(response.get_json()["status"], "unverified")

    def test_complete_flags_are_required(self):
        self.evidence(certify=False)
        response = self.request()
        self.assertEqual(response.get_json()["status"], "incomplete_cost_or_revenue_evidence")
        self.assertIsNone(response.get_json()["net_profit_usd"])

    def test_missing_source_coverage_blocks_month_certification(self):
        record = self.evidence()
        del record["reconciliation"]["revenue_sources"]["clickbank"]
        self.save_evidence(record)
        data = self.request().get_json()
        self.assertFalse(data["source_status"]["reconciliation_complete"])
        self.assertEqual(data["verification_status"], "PARTIAL")
        self.assertIsNone(data["net_profit_usd"])
        self.assertIsNone(data["visitor_target_met"])

    def test_unreconciled_bank_or_cost_category_blocks_certification(self):
        record = self.evidence()
        record["reconciliation"]["bank_reconciled"] = False
        self.save_evidence(record)
        data = self.request().get_json()
        self.assertFalse(data["source_status"]["reconciliation_complete"])
        self.assertIsNone(data["net_profit_per_visitor_usd"])

        record = self.evidence()
        del record["reconciliation"]["cost_categories"]["hosting"]
        self.save_evidence(record)
        data = self.request().get_json()
        self.assertFalse(data["source_status"]["reconciliation_complete"])
        self.assertIsNone(data["net_profit_usd"])

    def test_invalid_accounting_basis_does_not_break_reporting(self):
        record = self.evidence()
        record["reconciliation"]["accounting_basis"] = {}
        self.save_evidence(record)
        data = self.request().get_json()
        self.assertFalse(data["source_status"]["reconciliation_complete"])
        self.assertIsNone(data["net_profit_usd"])

    def test_reconciliation_must_be_after_month_close(self):
        record = self.evidence()
        record["reconciled_at"] = "2025-04-30T23:59:59Z"
        self.save_evidence(record)
        data = self.request().get_json()
        self.assertFalse(data["source_status"]["reconciliation_complete"])
        self.assertIsNone(data["net_profit_usd"])

    def test_future_month_cannot_be_verified(self):
        self.evidence(period="2099-01")
        response = self.request(period="2099-01")
        self.assertEqual(response.get_json()["status"], "reporting_period_open")
        self.assertIsNone(response.get_json()["net_profit_usd"])

    def test_certified_aggregate_visitor_counts_without_fake_pageviews(self):
        record = self.evidence()
        record["aggregate_counts"] = {
            "unique_visitors": 100,
            "unique_qualified_leads": 4,
            "visitor_source": "ga4:546929929",
            "lead_source": "reconciled_nija_crm",
        }
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        data = self.request().get_json()
        self.assertEqual(data["status"], "verified")
        self.assertEqual(data["unique_visitors"], 100)
        self.assertEqual(data["unique_qualified_leads"], 4)
        self.assertEqual(data["net_profit_per_visitor_usd"], "0.06")
        self.assertEqual(data["net_profit_per_qualified_lead_usd"], "1.50")
        self.assertEqual(data["visitor_count_source"], "certified_aggregate")

    def test_unattested_leads_have_no_profit_ratio(self):
        record = self.evidence()
        record["certification"]["qualified_leads_verified"] = False
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        data = self.request().get_json()
        self.assertEqual(data["status"], "verified")
        self.assertEqual(data["net_profit_per_visitor_usd"], "3.00")
        self.assertIsNone(data["net_profit_per_qualified_lead_usd"])
        self.assertIsNone(data["revenue_per_qualified_lead_usd"])

    def test_rejects_certified_aggregate_smaller_than_observed(self):
        record = self.evidence()
        record["aggregate_counts"] = {"unique_visitors": 1}
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        response = self.request()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "invalid_evidence")

    def test_invalid_period_rejected(self):
        response = self.request(period="../2025-04")
        self.assertEqual(response.status_code, 400)

    def test_symlink_evidence_is_not_trusted(self):
        external = Path(self.tempdir.name, "realfile.json")
        external.write_text("{}", encoding="utf-8")
        Path(self.tempdir.name, "2025-04.json").symlink_to(external)
        response = self.request()
        self.assertEqual(response.get_json()["status"], "unverified")

    def test_malformed_evidence_returns_invalid_not_500(self):
        record = self.evidence()
        record["cost_events"][0]["amount_usd"] = "invalid"
        record["signature"] = sign_evidence(record, self.key)
        Path(self.tempdir.name, "2025-04.json").write_text(json.dumps(record), encoding="utf-8")
        response = self.request()
        self.assertEqual(response.get_json()["status"], "incomplete_cost_or_revenue_evidence")
        self.assertIsNone(response.get_json()["net_profit_usd"])


if __name__ == "__main__":
    unittest.main()
