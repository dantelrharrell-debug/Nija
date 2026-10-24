"""Regression tests for startup certification diagnostics (never order authority)."""
import unittest
from unittest.mock import patch

from bot.execution_admission_acceptance_v468 import inspect_execution_admission
from bot.pretrade_independent_attestation import FIELDS


class StartupAdmissionReviewTests(unittest.TestCase):
    def inspect(self, checks, writer=True, kill=True, execution=False):
        attestation = {
            "checks": checks,
            "producer_status": "checks_passed_diagnostic_only" if all(checks.values()) else "checks_incomplete",
            "collector_installed": True,
        }
        with (
            patch("bot.pretrade_independent_attestation.inspect_authenticated_attestations", return_value=attestation),
            patch("preactivation_readiness_convergence_v16_patch._strict_authority_ready", return_value=(writer, "writer")),
            patch("preactivation_readiness_convergence_v16_patch._kill_switch_clear", return_value=(kill, "kill")),
            patch("preactivation_readiness_convergence_v16_patch._genuine_execution_marker_proof", return_value=(execution, "proof")),
        ):
            return inspect_execution_admission("platform:kraken")

    def test_certified_startup_does_not_authorize_orders(self):
        result = self.inspect({field: True for field in FIELDS})
        self.assertTrue(result["startup_certification_eligible"])
        self.assertTrue(result["startup_admission_migration_required"])
        self.assertFalse(result["eligible_for_existing_gate"])
        self.assertFalse(result["authorizes_orders"])

    def test_missing_certification_fails_closed(self):
        checks = {field: True for field in FIELDS}
        checks["protective_exit_readback"] = False
        result = self.inspect(checks)
        self.assertFalse(result["startup_certification_eligible"])
        self.assertFalse(result["authorizes_orders"])

    def test_writer_and_kill_switch_are_mandatory(self):
        checks = {field: True for field in FIELDS}
        for writer, kill in ((False, True), (True, False)):
            result = self.inspect(checks, writer=writer, kill=kill)
            self.assertFalse(result["startup_certification_eligible"])
            self.assertFalse(result["authorizes_orders"])

    def test_existing_gate_requires_real_execution_proof(self):
        result = self.inspect({field: True for field in FIELDS}, execution=True)
        self.assertTrue(result["eligible_for_existing_gate"])
        self.assertFalse(result["startup_admission_migration_required"])
        self.assertFalse(result["authorizes_orders"])


if __name__ == "__main__":
    unittest.main()
