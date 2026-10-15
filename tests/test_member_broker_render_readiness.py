"""Exercise the actual workflow diagnostic offline without real credentials."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import urllib.error


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/member-broker-render-readiness.yml"
REQUIRED_NAMES = (
    "NIJA_POCKETBASE_URL",
    "NIJA_BROKER_VAULT_KEY_B64",
    "NIJA_VAULT_BILLING_READONLY_URL",
    "NIJA_VAULT_STRIPE_READONLY_KEY",
    "NIJA_VAULT_FOUNDING_PRICE_ID",
    "NIJA_VAULT_FOUNDING_PRODUCT_ID",
    "NIJA_VAULT_INTAKE_ENABLED",
    "NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED",
    "NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED",
)


class RenderReadinessTests(unittest.TestCase):
    """Keep optional diagnostics distinct from successful readiness checks."""

    def _run_diagnostic(self, data=None, key="offline-test-key", error=None, summary=None):
        source = WORKFLOW.read_text(encoding="utf-8").split("python - <<'PY'\n", 1)[1]
        source = textwrap.dedent(source).rsplit("\nPY", 1)[0]
        env = {"RENDER_API_KEY": key}
        if summary is not None:
            env["GITHUB_STEP_SUMMARY"] = str(summary)
        output = io.StringIO()
        response = io.StringIO(json.dumps(data))
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(output):
            with patch("urllib.request.urlopen", return_value=response, side_effect=error) as request:
                with self.assertRaises(SystemExit) as result:
                    exec(compile(source, str(WORKFLOW), "exec"), {})
        self.assertNotIn("offline-test-key", output.getvalue())
        self.assertNotIn("private-env-value", output.getvalue())
        return result.exception.code, output.getvalue(), request

    def test_missing_secret_skips_without_api_call_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary"
            code, output, request = self._run_diagnostic(key="", summary=summary)
            self.assertEqual(code, 0)
            self.assertIn("::notice::SKIPPED:", output)
            self.assertIn("readiness was not checked", summary.read_text(encoding="utf-8"))
            self.assertIn("Actions repository secret RENDER_API_KEY", output)
            request.assert_not_called()

    def test_missing_secret_without_summary_also_skips(self):
        code, output, request = self._run_diagnostic(key="")
        self.assertEqual(code, 0)
        self.assertIn("SKIPPED:", output)
        request.assert_not_called()

    def test_configured_secret_checks_all_names_without_values(self):
        for wrapped in (True, False):
            with self.subTest(wrapped=wrapped):
                data = [{"key": name, "value": "private-env-value"} for name in REQUIRED_NAMES]
                if wrapped:
                    data = [{"envVar": item} for item in data]
                code, output, request = self._run_diagnostic(data)
                self.assertEqual(code, 0)
                self.assertIn("Missing variable names: none", output)
                self.assertNotIn("SKIPPED", output)
                req = request.call_args.args[0]
                self.assertEqual(req.get_header("Authorization"), "Bearer " + "offline-test-key")
                self.assertEqual(
                    req.full_url,
                    "https://api.render.com/v1/services/srv-db84gj5g1s2s7390mrp0/env-vars?limit=100",
                )
                self.assertEqual(request.call_args.kwargs["timeout"], 20)

    def test_missing_required_name_still_fails(self):
        data = [{"key": name} for name in REQUIRED_NAMES[:-1]]
        code, output, _ = self._run_diagnostic(data)
        self.assertEqual(code, 2)
        self.assertIn("Missing variable names: NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED", output)

    def test_api_errors_still_fail_without_disclosing_response(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                error = urllib.error.HTTPError(
                    "https://api.render.com", status, "private-env-value", {}, None,
                )
                code, output, _ = self._run_diagnostic(error=error)
                self.assertEqual(code, 2)
                self.assertIn(f"Render API request returned HTTP {status}", output)

    def test_network_errors_still_fail_without_disclosing_details(self):
        code, output, _ = self._run_diagnostic(error=OSError("private-env-value"))
        self.assertEqual(code, 2)
        self.assertIn("Could not contact Render API", output)

    def test_unexpected_response_still_fails_without_disclosing_payload(self):
        code, output, _ = self._run_diagnostic({"error": "private-env-value"})
        self.assertEqual(code, 2)
        self.assertIn("Unexpected Render API response format", output)


if __name__ == "__main__":
    unittest.main()
