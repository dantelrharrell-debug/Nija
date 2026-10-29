"""Exchange errors stay actionable without publishing upstream free text."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = runpy.run_path(str(ROOT / "scripts/nija_kraken_readonly_history_collector_v441.py"))
TRIAGE = runpy.run_path(str(ROOT / "scripts/nija_kraken_failure_receipt_triage_v464.py"))


class ApiFailureDiagnosticsTests(unittest.TestCase):
    def diagnose(self, payload, **options):
        calls = []

        def read(endpoint, params):
            calls.append(endpoint)
            return payload

        with self.assertRaises(COLLECTOR["IncompleteHistory"]) as caught:
            COLLECTOR["collect_history"](read, account_scope="platform:kraken", **options)
        self.assertEqual(len(calls), 1)  # No retry, fallback or side effect.
        exc = caught.exception
        self.assertEqual(str(exc), calls[0] + ": API failure")
        return COLLECTOR["history_failure_diagnostic"](exc)

    def test_known_errors_are_preserved_as_fixed_reasons(self):
        for error, reason in COLLECTOR["_API_ERROR_REASONS"].items():
            for options, endpoint in [({}, "TradesHistory"), ({"use_cursor": True}, "TradesHistory"),
                                      ({"include_balance": True}, "Balance")]:
                with self.subTest(error=error, options=options):
                    self.assertEqual(self.diagnose({"error": [error]}, **options), {
                        "error_code": "api_failure", "error_endpoint": endpoint,
                        "api_failure_reason": reason,
                    })

    def test_unknown_free_text_never_enters_diagnostic_or_exception(self):
        for error in ["credential-material", "EGeneral:Permission denied secret-material",
                      "EAPI:Invalid nonce\naccount-material", "EService: Throttled: secret-material"]:
            diagnostic = self.diagnose({"error": [error], "result": {"secret": error}})
            self.assertEqual(diagnostic["api_failure_reason"], "unknown_api_error")
            self.assertNotIn(error, json.dumps(diagnostic))

    def test_throttle_time_is_not_serialized(self):
        for value in ["EService: Throttled: 1793270000", "EService:Throttled: 1793270000"]:
            diagnostic = self.diagnose({"error": [value]})
            self.assertEqual(diagnostic["api_failure_reason"], "throttled")
            self.assertNotIn("1793270000", json.dumps(diagnostic))

    def test_malformed_and_multiple_errors_are_not_guessed(self):
        for value in [None, {}, {"result": {"count": 0, "trades": {}}}, {"error": None}, {"error": "EAPI:Invalid key"}, {"error": [123]}]:
            self.assertEqual(self.diagnose(value)["api_failure_reason"], "malformed_api_response")
        self.assertEqual(self.diagnose({"error": ["EAPI:Invalid nonce", "arbitrary"]})[
            "api_failure_reason"], "multiple_api_errors")

    def test_open_orders_read_uses_same_classifier(self):
        calls = []
        def read(endpoint, params):
            calls.append(endpoint)
            if endpoint == "OpenOrders":
                return {"error": ["EGeneral:Permission denied"]}
            field = dict(COLLECTOR["ENDPOINTS"])[endpoint]
            return {"error": [], "result": {"count": 0, field: {}}}
        with self.assertRaises(COLLECTOR["IncompleteHistory"]) as caught:
            COLLECTOR["collect_history"](read, account_scope="platform:kraken", include_open_orders=True)
        self.assertEqual(COLLECTOR["history_failure_diagnostic"](caught.exception), {
            "error_code": "api_failure", "error_endpoint": "OpenOrders",
            "api_failure_reason": "permission_denied",
        })
        self.assertEqual(calls.count("OpenOrders"), 1)

    def test_forged_exception_attribute_is_not_published(self):
        exc = COLLECTOR["IncompleteHistory"]("TradesHistory: API failure", api_failure_reason="secret")
        self.assertIsNone(exc.api_failure_reason)
        exc.api_failure_reason = "secret"
        self.assertNotIn("api_failure_reason", COLLECTOR["history_failure_diagnostic"](exc))

    def test_triage_contract_and_legacy_receipts(self):
        self.assertEqual(TRIAGE["API_FAILURE_REASONS"], COLLECTOR["API_FAILURE_REASONS"])
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            request_id = "a" * 32
            claim = {"request_id": request_id, "account_scope": "platform:kraken",
                     "created_at": 1000, "max_pages": 100}
            receipt = {"request_id": request_id, "collection_succeeded": False,
                       "trading_authorized": False, "error_type": "IncompleteHistory",
                       "error_code": "api_failure", "error_endpoint": "TradesHistory"}
            def write(suffix, value):
                path = root / (request_id + suffix)
                path.write_text(json.dumps(value))
                path.chmod(0o600)
            write(".claimed.json", claim)
            write(".evidence.json", receipt)
            self.assertNotIn("api_failure_reason", TRIAGE["inspect_failure"](root, request_id))
            for cursor in (False, True):
                claim["use_cursor"] = cursor
                write(".claimed.json", claim)
                self.assertEqual(TRIAGE["inspect_failure"](root, request_id)["failure_code"], "api_failure")
            claim["use_cursor"] = "false"
            write(".claimed.json", claim)
            with self.assertRaises(TRIAGE["TriageFailure"]):
                TRIAGE["inspect_failure"](root, request_id)
            claim["use_cursor"] = False
            write(".claimed.json", claim)
            receipt["api_failure_reason"] = "invalid_nonce"
            write(".evidence.json", receipt)
            self.assertEqual(TRIAGE["inspect_failure"](root, request_id)["api_failure_reason"], "invalid_nonce")
            for code, reason in [("api_failure", "secret"), ("invalid_cursor", "invalid_nonce"),
                                 ("api_failure", None), ("api_failure", ["invalid_nonce"])]:
                receipt.update(error_code=code, api_failure_reason=reason)
                write(".evidence.json", receipt)
                with self.assertRaises(TRIAGE["TriageFailure"]):
                    TRIAGE["inspect_failure"](root, request_id)


if __name__ == "__main__":
    unittest.main()
