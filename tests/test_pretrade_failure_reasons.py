"""Synthetic, non-authorizing coverage for every independent certificate field."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

from bot.pretrade_attestation_validation_v452 import (
    IndependentEvidenceRejected, PROOF_BY_SOURCE, REQUIRED, SOURCES,
    evaluate_pretrade_certificate,
)
from bot.pretrade_authenticated_provider_adapter_v453 import collect_independent_pretrade_evidence
from bot.pretrade_composition_bridge_v465 import make_collector
from bot.pretrade_independent_attestation import inspect_authenticated_attestations


class FailureReasonTests(unittest.TestCase):
    """Diagnostics retain exact field attribution without exposing upstream data."""

    def setUp(self) -> None:
        self.now = time.time()
        self.account = "platform:kraken"
        self.trusted = {field: "reviewed-" + field for field in REQUIRED}
        self.rows = {
            field: {
                "account": self.account, "source": SOURCES[field],
                "provider_id": self.trusted[field], "evidence_id": "receipt-" + field,
                "verified": True, "read_only": True, "scope_verified": True,
                "observed_at_epoch": self.now,
                "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, "complete_pagination_verified": True,
                    PROOF_BY_SOURCE[SOURCES[field]]: True,
                },
            } for field in REQUIRED
        }

    def evaluate(self, rows: dict) -> dict:
        """Evaluate synthetic inputs at a fixed clock."""
        return evaluate_pretrade_certificate(
            rows, account=self.account, trusted_provider_ids=self.trusted, now_epoch=self.now,
        )

    def test_all_thirteen_checks_pass_without_order_authority(self) -> None:
        result = self.evaluate(self.rows)
        self.assertTrue(result["certified"])
        self.assertEqual(result["failure_reasons"], {})
        self.assertFalse(result["authorizes_orders"])

    def test_each_field_is_required_and_account_bound(self) -> None:
        for field in REQUIRED:
            for key, value, reason in (
                ("account", "user:someone:kraken", "account_scope_mismatch"),
                ("verified", False, "observation_not_verified"),
                ("read_only", False, "read_only_unverified"),
                ("scope_verified", None, "scope_unverified"),
                ("source", "not-trusted", "source_mismatch"),
                ("provider_id", "not-reviewed", "provider_identity_mismatch"),
                ("evidence_id", "", "evidence_identity_missing"),
                ("provenance", None, "provenance_missing"),
                ("observed_at_epoch", self.now - 61, "observation_stale"),
                ("observed_at_epoch", self.now + 1, "observation_future"),
                ("observed_at_epoch", True, "observation_clock_invalid"),
            ):
                with self.subTest(field=field, key=key, reason=reason):
                    rows = deepcopy(self.rows)
                    rows[field][key] = value
                    result = self.evaluate(rows)
                    self.assertFalse(result["certified"])
                    self.assertEqual(result["missing"], [field])
                    self.assertEqual(result["failure_reasons"], {field: reason})
                    self.assertFalse(result["authorizes_orders"])
            rows = deepcopy(self.rows)
            del rows[field]
            self.assertEqual(self.evaluate(rows)["failure_reasons"], {field: "observation_missing"})

    def test_each_source_requires_its_own_complete_provenance(self) -> None:
        for field in REQUIRED:
            for key, reason in (
                ("account_scope_verified", "account_provenance_unverified"),
                ("collector_identity_verified", "collector_identity_unverified"),
                ("snapshot_complete", "snapshot_incomplete"),
                (PROOF_BY_SOURCE[SOURCES[field]], "source_proof_unverified"),
            ):
                rows = deepcopy(self.rows)
                rows[field]["provenance"][key] = False
                self.assertEqual(self.evaluate(rows)["failure_reasons"], {field: reason})
            if SOURCES[field] in {"authenticated_broker", "independent_ledger"}:
                rows = deepcopy(self.rows)
                rows[field]["provenance"]["complete_pagination_verified"] = False
                self.assertEqual(self.evaluate(rows)["failure_reasons"], {field: "pagination_incomplete"})

    def test_reused_receipt_rejects_both_conflicting_fields(self) -> None:
        self.rows["position_sync"]["evidence_id"] = self.rows["broker_balances"]["evidence_id"]
        result = self.evaluate(self.rows)
        self.assertEqual(result["failure_reasons"], {
            "broker_balances": "evidence_identity_reused", "position_sync": "evidence_identity_reused",
        })

    def test_missing_and_failed_readers_are_not_observations(self) -> None:
        providers = {field: (lambda row=row: deepcopy(row)) for field, row in self.rows.items()}
        del providers["position_ledger_reconciliation"]
        providers["risk_limits"] = lambda: None

        def fail() -> None:
            raise RuntimeError("private-upstream-canary")

        providers["kill_switch_clear"] = fail
        report = collect_independent_pretrade_evidence(
            providers, account=self.account, trusted_provider_ids=self.trusted, now_epoch=self.now,
        )
        self.assertEqual(report["certificate"]["failure_reasons"], {
            "position_ledger_reconciliation": "independent_provider_missing",
            "risk_limits": "provider_result_invalid", "kill_switch_clear": "provider_read_failed",
        })
        self.assertNotIn("private-upstream-canary", str(report))

    def test_bridge_preserves_reason_but_not_raw_exception(self) -> None:
        self.rows["operator_authorization"]["verified"] = False
        providers = {field: (lambda row=row: deepcopy(row)) for field, row in self.rows.items()}
        collector = make_collector({self.account: providers}, trusted_provider_ids=self.trusted)
        with patch("bot.pretrade_independent_attestation._COLLECTOR", collector):
            report = inspect_authenticated_attestations(self.account)
        self.assertFalse(any(report["checks"].values()))
        self.assertEqual(report["failure_reasons"], {
            field: "observation_not_verified" if field == "operator_authorization"
            else "independent_evidence_rejected" for field in REQUIRED
        })
        self.assertFalse(report["authorizes_orders"])
        exc = IndependentEvidenceRejected(["risk_limits"], {"risk_limits": "private-upstream-canary"})
        self.assertEqual(exc.failure_reasons, {"risk_limits": "certificate_context_unverified"})

    def test_missing_collector_names_every_unverified_field(self) -> None:
        with patch("bot.pretrade_independent_attestation._COLLECTOR", None):
            report = inspect_authenticated_attestations(self.account)
        self.assertEqual(report["failure_reasons"], {field: "collector_missing" for field in REQUIRED})
        self.assertFalse(report["collector_installed"])

    def test_runtime_logs_only_allowlisted_field_reasons(self) -> None:
        import preactivation_readiness_convergence_v16_patch as runtime

        report = {
            "checks": {field: False for field in REQUIRED},
            "collector_installed": True, "producer_status": "independent_evidence_rejected",
            "failure_reasons": {
                "risk_limits": "observation_stale",
                "operator_authorization": "private-upstream-canary",
                "private-upstream-canary": "provider_read_failed",
            },
        }
        with patch.dict("os.environ", {"NIJA_PREFLIGHT_ACCOUNT_SCOPE": self.account}), patch(
            "bot.pretrade_independent_attestation.inspect_authenticated_attestations", return_value=report,
        ), self.assertLogs("nija.preactivation_readiness_convergence_v16", level="INFO") as logs:
            ready, missing = runtime._independent_pretrade_certificate()
        self.assertFalse(ready)
        self.assertEqual(missing, list(REQUIRED))
        self.assertIn("risk_limits:observation_stale", str(logs.output))
        self.assertIn("producer_status=independent_evidence_rejected", str(logs.output))
        self.assertNotIn("private-upstream-canary", str(logs.output))
