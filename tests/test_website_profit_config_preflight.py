"""Synthetic regression checks for value-free billing configuration preflight."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.website_profit_config_preflight import preflight


class ProfitConfigPreflightTests(unittest.TestCase):
    def test_absence_is_reported_without_certification(self):
        result = preflight({}, "2026-10")
        self.assertEqual(result["dashboard_token"], "missing")
        self.assertEqual(result["evidence_directory"], "missing")
        self.assertFalse(result["financial_certification"])

    def test_only_metadata_is_used_and_no_values_are_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "2026-10.json"
            evidence.write_text("Not valid JSON; the operator check must not parse it.")
            token, signer = "synthetic-A" * 4, "synthetic-B" * 4
            with patch.object(Path, "open", side_effect=AssertionError("opening evidence is forbidden")):
                result = preflight({
                    "NIJA_PROFIT_DASHBOARD_TOKEN": token,
                    "NIJA_PROFIT_EVIDENCE_HMAC_KEY": signer,
                    "NIJA_PROFIT_EVIDENCE_DIR": directory,
                }, "2026-10")
            self.assertEqual(result["period_file"], "readable_metadata_only")
            self.assertEqual(result["key_separation"], "distinct")
            self.assertFalse(result["financial_certification"])
            for value in (token, signer, directory, evidence.name):
                self.assertNotIn(value, json.dumps(result))

    def test_equal_short_and_non_ascii_keys_have_fixed_states(self):
        env = {
            "NIJA_PROFIT_DASHBOARD_TOKEN": "x" * 64,
            "NIJA_PROFIT_EVIDENCE_HMAC_KEY": "x" * 64,
        }
        self.assertEqual(preflight(env, "2026-10")["key_separation"], "matching")
        env["NIJA_PROFIT_EVIDENCE_HMAC_KEY"] = "too short"
        self.assertEqual(preflight(env, "2026-10")["evidence_signing_key"], "below_minimum")
        env["NIJA_PROFIT_EVIDENCE_HMAC_KEY"] = "é" * 40
        self.assertEqual(preflight(env, "2026-10")["evidence_signing_key"], "non_ascii")

    def test_rejects_symlink_and_invalid_period(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2026-10.json").symlink_to(root / "target")
            result = preflight({"NIJA_PROFIT_EVIDENCE_DIR": directory}, "2026-10")
            self.assertEqual(result["period_file"], "not_regular_file")
        with self.assertRaises(ValueError):
            preflight({}, "../2026-10")
