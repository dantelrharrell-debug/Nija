"""Regression checks for capital coordinator fail-closed outcome diagnostics.

These source-level checks intentionally avoid broker network access or order placement.
"""
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "capital_flow_state_machine.py"


class CapitalCoordinatorOutcomeDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_outcomes_distinguish_failure_modes(self):
        for reason in (
            "reason=in_flight",
            "reason=pipeline_exception",
            "reason=publication_lock_timeout",
            "reason=publication_rejected",
            "reason=post_publish_stale",
            '"snapshot_accepted" if result is not None else "pipeline_returned_none"',
        ):
            with self.subTest(reason=reason):
                self.assertIn(reason, self.source)

    def test_single_writer_and_rejection_remain(self):
        self.assertIn("if self._in_flight:", self.source)
        self.assertIn("authority.publish_snapshot(snapshot, writer_id=self.WRITER_ID)", self.source)
        self.assertIn("if not accepted:", self.source)
        self.assertIn('self._bus.request_refresh("stale_snapshot_post_publish")', self.source)

    def test_diagnostics_do_not_log_secret_values(self):
        self.assertNotIn("CAPITAL_COORDINATOR_OUTCOME secret=", self.source)
        self.assertNotIn("CAPITAL_COORDINATOR_OUTCOME api_key=", self.source)


if __name__ == "__main__":
    unittest.main()
