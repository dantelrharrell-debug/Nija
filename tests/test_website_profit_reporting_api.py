"""Security and financial-integrity tests for the read-only website profit API."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

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
            {"type": "qualified_lead", "event_id": "l-1", "lead_id": "lead-1", "visitor_id": "visitor-1", "period": period},
            {"type": "revenue", "event_id": "stripe-1", "source": "stripe", "verified": True, "amount_usd": "12.00", "period": period},
            {"type": "refund", "event_id": "stripe-refund-1", "source": "stripe", "verified": True, "amount_usd": "2.00", "period": period},
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
                "provider_revenue_verified": certify,
                "all_costs_verified": certify,
            },
        }
        body["signature"] = sign_evidence(body, self.key)
        Path(self.tempdir.name, period + ".json").write_text(json.dumps(body), encoding="utf-8")
        return body

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
        self.assertIsNone(response.get_json()["net_profit_usd"])

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

    def test_future_month_cannot_be_verified(self):
        self.evidence(period="2099-01")
        response = self.request(period="2099-01")
        self.assertEqual(response.get_json()["status"], "reporting_period_open")
        self.assertIsNone(response.get_json()["net_profit_usd"])

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
