"""Regression gates for NIJA revenue dashboard certification.

Synthetic fixtures only; no live credentials, payments or provider calls.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from flask import Flask
from website_profit_dashboard import create_dashboard_blueprint
from website_profit_reporting_api import create_profit_blueprint


class RevenueCertificationBoundaryTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.testing = True
        app.register_blueprint(create_dashboard_blueprint())
        app.register_blueprint(create_profit_blueprint())
        self.client = app.test_client()

    def test_unconfigured_reporting_never_exposes_financial_values(self):
        with patch.dict(os.environ, {
            "NIJA_PROFIT_DASHBOARD_TOKEN": "",
            "NIJA_PROFIT_EVIDENCE_HMAC_KEY": "",
            "NIJA_PROFIT_EVIDENCE_DIR": "",
        }):
            response = self.client.get("/api/admin/website-profit?period=2026-10")
        self.assertEqual(response.status_code, 503)
        body = response.get_json()
        self.assertEqual(body["status"], "unavailable")
        for forbidden in ("net_profit_usd", "net_profit_per_visitor_usd", "visitor_target_met"):
            self.assertNotIn(forbidden, body)

    def test_dashboard_is_no_store_and_does_not_embed_credentials(self):
        with patch.dict(os.environ, {"NIJA_PROFIT_DASHBOARD_TOKEN": "test-only-secret-" + "x" * 40}):
            response = self.client.get("/admin/revenue-per-visitor")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store, private")
        self.assertNotIn("test-only-secret-", response.get_data(as_text=True))

    def test_rolling_week_is_not_misrepresented_as_closed_month(self):
        with patch.dict(os.environ, {
            "NIJA_PROFIT_DASHBOARD_TOKEN": "test-token-" + "x" * 40,
            "NIJA_PROFIT_EVIDENCE_HMAC_KEY": "test-signing-" + "y" * 40,
            "NIJA_PROFIT_EVIDENCE_DIR": "/tmp/nija-nonexistent-profit-evidence-test",
        }):
            response = self.client.get(
                "/api/admin/website-profit?period=2026-10-30",
                headers={"Authorization": "Bearer " + "test-token-" + "x" * 40},
            )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
