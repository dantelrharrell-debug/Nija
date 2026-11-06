"""Offline tests for the credential-free profit dashboard probe."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from email.message import Message

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_profit_dashboard_public_routes.py"
spec = importlib.util.spec_from_file_location("profit_probe", SCRIPT)
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


class Response:
    status = 200
    headers = {"Cache-Control": "no-store, private", "Content-Type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ProbeTests(unittest.TestCase):
    def test_rejects_unsafe_origins(self):
        for origin in ("http://example.com", "https://user:secret@example.com", "https://example.com/path", "https://example.com?token=x"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                probe_module.probe(origin)

    def test_no_credentials_or_write_requests(self):
        requests = []

        def fake_open(request, timeout):
            requests.append(request)
            if len(requests) == 2:
                raise HTTPError(request.full_url, 503, "unavailable", Message(), None)
            return Response()

        with patch.object(probe_module, "urlopen", side_effect=fake_open):
            result = probe_module.probe()
        self.assertEqual(result["dashboard"]["http_status"], 200)
        self.assertEqual(result["profit_api_without_credentials"]["http_status"], 503)
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.get_header("Authorization"))
            self.assertNotIn("token=", request.full_url)


if __name__ == "__main__":
    unittest.main()
