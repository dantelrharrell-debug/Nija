"""Synthetic offline checks for the isolated Nija Render WSGI entrypoint."""

import json
import unittest
from wsgiref.util import setup_testing_defaults

from nija_app import app


class NijaRenderEntrypointTests(unittest.TestCase):
    def request(self, path="/healthz", method="GET"):
        environ = {}
        setup_testing_defaults(environ)
        environ.update({"REQUEST_METHOD": method, "PATH_INFO": path})
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        result = b"".join(app(environ, start_response))
        return captured["status"], captured["headers"], result

    def test_health_routes_work_without_credentials(self):
        for path in ("/health", "/healthz"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, "200 OK")
                self.assertEqual(json.loads(body)["component"], "http_liveness")
                self.assertEqual(headers["Cache-Control"], "no-store")

    def test_status_discloses_no_sensitive_account_data(self):
        status, headers, body = self.request("/status")
        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body)["account_listing"], "disabled")
        self.assertNotIn(b"balance", body)
        self.assertNotIn(b"credential", body)

    def test_legacy_public_accounts_are_not_exposed(self):
        status, _, body = self.request("/")
        self.assertEqual(status, "503 Service Unavailable")
        self.assertEqual(json.loads(body)["error"], "private_account_listing_disabled")

    def test_unknown_routes_and_methods_rejected(self):
        self.assertEqual(self.request("/accounts")[0], "404 Not Found")
        status, headers, _ = self.request("/healthz", "POST")
        self.assertEqual(status, "405 Method Not Allowed")
        self.assertEqual(headers["Allow"], "GET, HEAD")

    def test_head_response_body_is_empty(self):
        status, headers, body = self.request("/healthz", "HEAD")
        self.assertEqual(status, "200 OK")
        self.assertEqual(body, b"")
        self.assertGreater(int(headers["Content-Length"]), 0)


if __name__ == "__main__":
    unittest.main()
