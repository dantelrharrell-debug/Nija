"""Read-only canonical Trading IQ release gates. No network, credentials or publishing."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CanonicalGameEvidenceTests(unittest.TestCase):
    def test_served_game_is_not_claimed_as_preview(self):
        readme = (ROOT / "game_sandbox/README.md").read_text()
        self.assertIn("72 decisions", readme)
        self.assertIn("equivalence to the latest inaccessible IONOS preview remains unverified", readme)

    def test_published_parity_is_scoped_to_served_reducer(self):
        test = (ROOT / "game_sandbox/ionos_parity.test.mjs").read_text()
        self.assertIn("ionos_served_ui_reference.mjs", test)
        self.assertIn("i < 72", test)
        self.assertIn("assert.equal(state.decLog.length, 72)", test)

    def test_canonical_export_is_not_implicitly_available(self):
        plan = (ROOT / "docs/trading_iq_unified_upgrade_plan_20261108.md").read_text()
        self.assertIn("Export canonical IONOS", plan)
        self.assertIn("Do not assume", plan)

if __name__ == "__main__":
    unittest.main()
