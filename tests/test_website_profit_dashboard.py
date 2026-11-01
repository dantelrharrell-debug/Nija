"""Security and behavior tests for the static NIJA profit dashboard shell."""
from __future__ import annotations

import os
import re
import unittest
from unittest.mock import patch

from flask import Flask

from website_profit_dashboard import create_dashboard_blueprint
from website_profit_reporting_api import create_profit_blueprint


class WebsiteProfitDashboardTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.testing = True
        app.register_blueprint(create_dashboard_blueprint())
        app.register_blueprint(create_profit_blueprint())
        self.client = app.test_client()

    def test_public_html_shell_is_read_only_and_never_contains_financial_records(self):
        with patch.dict(os.environ, {
            "NIJA_PROFIT_DASHBOARD_TOKEN": "private-admin-token-" + "x"*50,
            "NIJA_PROFIT_EVIDENCE_HMAC_KEY": "private-evidence-signing-key-" + "z"*50,
        }):
            response = self.client.get("/admin/revenue-per-visitor")
            html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)
        self.assertIn("UNVERIFIED", html)
        self.assertIn("Missing amounts are not zero", html)
        self.assertNotIn("private-admin-token", html)
        self.assertNotIn("private-evidence-signing", html)
        self.assertNotIn("customer@example.com", html)
        self.assertIn("/api/admin/website-profit?period=", html)
        self.assertIn('method:"GET"', html)
        self.assertIn("Authorization", html)
        self.assertIn('credentials:"omit"', html)
        self.assertIn("cache:\"no-store\"", html)
        self.assertIn("status.revenue_evidence_complete", html)
        self.assertIn("status.cost_evidence_complete", html)
        self.assertIn("status.reconciliation_complete===true", html)
        self.assertIn("status.reporting_period_closed", html)
        self.assertIn("status.qualified_leads_verified", html)
        self.assertIn("Missing or incomplete independently certified evidence", html)

    def test_html_security_headers_and_nonce(self):
        response = self.client.get("/admin/revenue-per-visitor")
        self.assertEqual(response.status_code, 200)
        headers = response.headers
        self.assertEqual(headers["Cache-Control"], "no-store, private")
        self.assertEqual(headers["Pragma"], "no-cache")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        csp = headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("form-action 'none'", csp)
        nonce = re.search(r"script-src 'nonce-([^']+)'", csp)
        self.assertIsNotNone(nonce)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count(f'nonce="{nonce.group(1)}"'), 2)
        self.assertNotIn("__NONCE__", html)

    def test_each_response_uses_new_nonce(self):
        first = self.client.get("/admin/revenue-per-visitor")
        second = self.client.get("/admin/revenue-per-visitor")
        self.assertNotEqual(first.headers["Content-Security-Policy"],
                            second.headers["Content-Security-Policy"])

    def test_dashboard_cannot_mutate_records(self):
        for method in ("post", "put", "patch", "delete"):
            result = getattr(self.client, method)("/admin/revenue-per-visitor")
            self.assertEqual(result.status_code, 405, method)

    def test_unknown_path_does_not_add_another_profit_endpoint(self):
        self.assertEqual(self.client.get("/admin/revenue-per-visitor/exports").status_code, 404)

    def test_profit_api_remains_fail_closed_with_no_keys(self):
        with patch.dict(os.environ, {
            "NIJA_PROFIT_DASHBOARD_TOKEN": "",
            "NIJA_PROFIT_EVIDENCE_HMAC_KEY": "",
            "NIJA_PROFIT_EVIDENCE_DIR": "",
        }):
            response = self.client.get("/api/admin/website-profit?period=2026-10")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("gross_collected_revenue_usd",
                         response.get_data(as_text=True))

    def test_profit_api_rejects_unauthorized_request_with_valid_configuration(self):
        with patch.dict(os.environ, {
            "NIJA_PROFIT_DASHBOARD_TOKEN": "tok-" + "x"*50,
            "NIJA_PROFIT_EVIDENCE_HMAC_KEY": "sig-" + "z"*50,
            "NIJA_PROFIT_EVIDENCE_DIR": "/tmp/not-existing-evidence-for-test",
        }):
            response = self.client.get("/api/admin/website-profit?period=2026-10")
        self.assertEqual(response.status_code, 401)

    def test_no_browser_persistent_storage_or_third_party_scripts(self):
        html = self.client.get("/admin/revenue-per-visitor").get_data(as_text=True)
        for forbidden in ("localStorage", "sessionStorage", "document.cookie", "https://hooks.",
                          "<iframe", "src=\"https://", "sendBeacon(", "gtag(",
                          "fetch(\"https://", "XMLHttpRequest("):
            self.assertNotIn(forbidden, html)
        self.assertIn('password.value=""', html)
        self.assertIn('document.getElementById("coverage")', html)


if __name__ == "__main__":
    unittest.main()
