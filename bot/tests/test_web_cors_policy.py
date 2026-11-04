"""Offline browser preflight regressions; no service or broker imports."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from web_cors_policy import allowed_web_origins

ROOT = Path(__file__).resolve().parents[2]
CORS_SURFACES = (
    "api_server.py", "mobile_backend_server.py", "billing_service.py", "gateway.py",
    "founder_dashboard.py", "control_center_api.py", "central_dashboard_api.py",
    "micro_cap_dashboard_api.py", "bot/command_center_api.py",
)


class WebCorsPolicyTests(unittest.TestCase):
    """Keep legitimate browser access without wildcard credential or PNA grants."""

    def test_default_and_explicit_development_origins(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(allowed_web_origins(), [
                "https://nijaaitrading.com", "https://www.nijaaitrading.com",
            ])
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": "https://app.example, http://localhost:3000"}):
            self.assertEqual(allowed_web_origins(), ["https://app.example", "http://localhost:3000"])

    def test_wildcards_patterns_empty_and_non_origins_fail_closed(self) -> None:
        for value in ("*", "", "https://trusted.example,*", "https://*.example", "https://a.example,",
                      "https://a.example/path", "https://a.example?token=x", "https://u:p@a.example",
                      "https://a.example?", "https://trusted.example?", "https://a.example#fragment",
                      "https://a.example:bad", "file:///tmp/index.html",
                      "https://a.example|https://evil.example", "https://a .example"):
            with self.subTest(value=value), patch.dict(os.environ, {"ALLOWED_ORIGINS": value}):
                with self.assertRaises(ValueError):
                    allowed_web_origins()

    def make_client(self):
        """Create a disposable Flask app using the real production CORS calls."""
        app = Flask(__name__)
        for filename in ("api_server.py", "mobile_backend_server.py"):
            tree = ast.parse((ROOT / filename).read_text())
            call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == "CORS")
            expression = ast.fix_missing_locations(ast.Expression(body=call))
            eval(compile(expression, filename, "eval"), {
                "app": app, "CORS": CORS, "_allowed_origins": ["https://trusted.example"],
            })

        @app.get("/api/offline")
        def offline():
            return {"offline": True}

        return app.test_client()

    def test_real_config_preserves_allowed_preflight_and_denies_private_network(self) -> None:
        client = self.make_client()
        response = client.options("/api/offline", headers={
            "Origin": "https://trusted.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://trusted.example")
        self.assertEqual(response.headers["Access-Control-Allow-Credentials"], "true")
        self.assertNotEqual(response.headers.get("Access-Control-Allow-Private-Network"), "true")

    def test_earlier_base_app_cors_cannot_reauthorize_a_denied_origin(self) -> None:
        client = self.make_client()
        for origin in (
            "https://evil.example", "https://trusted.example.evil.example",
            "https://trusted.example?", "null",
        ):
            response = client.get("/api/offline", headers={"Origin": origin})
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
            self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_every_existing_flask_cors_surface_explicitly_denies_private_network(self) -> None:
        for filename in CORS_SURFACES:
            tree = ast.parse((ROOT / filename).read_text())
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == "CORS"]
            self.assertTrue(calls, filename)
            for call in calls:
                policy = next((kw.value for kw in call.keywords if kw.arg == "allow_private_network"), None)
                self.assertIsInstance(policy, ast.Constant, filename)
                self.assertIs(policy.value, False, filename)

    def test_upgraded_socket_stack_preserves_threaded_offline_transport(self) -> None:
        app = Flask(__name__)
        socketio = SocketIO(app, async_mode="threading", cors_allowed_origins=["https://trusted.example"])

        @socketio.on("offline_ping")
        def ping(data):
            return {"received": data}

        client = socketio.test_client(app)
        try:
            self.assertTrue(client.is_connected())
            self.assertEqual(client.emit("offline_ping", {"offline": True}, callback=True),
                             {"received": {"offline": True}})
        finally:
            client.disconnect()


if __name__ == "__main__":
    unittest.main()
