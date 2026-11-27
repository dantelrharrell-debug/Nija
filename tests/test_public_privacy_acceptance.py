"""Synthetic/offline checks for NIJA public privacy and file access."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_public_privacy_access import (
    _manifest, _same_origin, evaluate_deletion, evaluate_free,
    evaluate_policy, evaluate_private, verify,
)


class PublicAcceptanceTests(unittest.TestCase):
    def test_policy_placeholder_denied(self):
        self.assertEqual(
            evaluate_policy(200, b"<h1>Privacy</h1>FULL POLICY PENDING")[1],
            "policy_placeholder")

    def test_policy_requires_date(self):
        self.assertEqual(
            evaluate_policy(200, b"Privacy retention account request")[1],
            "policy_effective_date_unverified")

    def test_policy_candidate(self):
        self.assertTrue(evaluate_policy(
            200, b"Privacy retention account request. Effective 2026-11-27")[0])

    def test_deletion_site_404_denied(self):
        self.assertEqual(evaluate_deletion(
            200, b"404 This page doesn't exist")[1], "deletion_site_404")

    def test_deletion_scope_required(self):
        self.assertFalse(evaluate_deletion(200, b"Delete account support")[0])

    def test_deletion_content_candidate(self):
        self.assertTrue(evaluate_deletion(
            200, b"Delete Your Account. Support. This does not cover all data.")[0])

    def test_private_requires_both_methods(self):
        self.assertTrue(evaluate_private(403, 404)[0])
        for statuses in ((200, 403), (403, 206), (302, 302), (405, 416)):
            with self.subTest(statuses=statuses):
                self.assertFalse(evaluate_private(*statuses)[0])

    def test_free_pdf_signature(self):
        self.assertTrue(evaluate_free(200, 206, b"%PDF-1.7")[0])
        self.assertFalse(evaluate_free(200, 206, b"<html>login")[0])

    def test_origin_validation(self):
        for value in ("http://nijaaitrading.com/x",
                      "https://different.example/x", "/paid?key=1",
                      "https://user:pwd@nijaaitrading.com/private"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _same_origin("https://nijaaitrading.com", value)
        self.assertEqual(_same_origin("https://nijaaitrading.com", "/x"),
                         "https://nijaaitrading.com/x")

    def test_duplicate_manifest_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "private.json")
            path.write_text(json.dumps(["/private/synthetic.mp4",
                                        "/private/synthetic.mp4"]))
            with self.assertRaisesRegex(ValueError, "duplicate_asset"):
                _manifest(path, "https://nijaaitrading.com")

    def test_private_url_is_never_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "private.json")
            path.write_text(json.dumps(["/private/owner-not-for-public.mp4"]))
            def stub(url, method, limit=0):
                if url.endswith("/privacy-policy"):
                    return 200, b"Privacy retention account request. Effective 2026-11-27"
                if url.endswith("/account-deletion"):
                    return 200, b"Delete account support. This does not cover other data."
                if "NIJA_Starter_Kit.pdf" in url:
                    return (200, b"") if method == "HEAD" else (206, b"%PDF-1.7")
                return (200, b"") if method == "HEAD" else (206, b"synthetic")
            with patch("scripts.check_public_privacy_access._read_status",
                       side_effect=stub):
                result = verify("https://nijaaitrading.com", path,
                                "/NIJA_Starter_Kit.pdf")
            self.assertEqual(result["outcome"], "fail")
            self.assertEqual(result["private_assets"]["failures"], 1)
            self.assertNotIn("owner-not-for-public", json.dumps(result))
            self.assertEqual(result["authorized_purchaser_access"], "not_tested")

    def test_missing_asset_manifest_is_partial_only(self):
        with patch("scripts.check_public_privacy_access._read_status",
                   side_effect=[
                     (200, b"Privacy retention account request. Effective 2026-11-27"),
                     (200, b"Delete account support. This does not cover all data.")]):
            result = verify("https://nijaaitrading.com", None, None)
        self.assertEqual(result["outcome"],
                         "partial_only_untested_assets_or_free_kit")


if __name__ == "__main__":
    unittest.main()
