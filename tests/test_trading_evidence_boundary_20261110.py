"""Read-only regression gates: fail closed until authenticated evidence is attested."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class ExecutionEvidenceBoundaryTests(unittest.TestCase):
    def test_collector_requires_trusted_account_scoped_reader(self):
        src = (ROOT / "scripts/nija_kraken_readonly_history_collector_v441.py").read_text()
        self.assertIn("private_read: Callable", src)
        self.assertIn("Explicit Kraken account scope required", src)
        self.assertIn("raise IncompleteHistory", src)
        self.assertNotIn("AddOrder", src)

    def test_entrypoint_preserves_no_force_activation(self):
        src = (ROOT / "scripts/render_entrypoint.sh").read_text()
        self.assertIn("export NIJA_FORCE_ACTIVATION=false", src)
        self.assertIn("export FORCE_TRADE=false", src)
        self.assertIn("export NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false", src)

if __name__ == "__main__":
    unittest.main()
