"""Regression tests for read-only Render startup-command attestation."""
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "check_render_command_drift.py"
spec = importlib.util.spec_from_file_location("check_render_command_drift", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CommandDriftTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(module.check("bash scripts/render_entrypoint.sh", "bash scripts/render_entrypoint.sh"), 0)

    def test_live_bootstrap_mismatch(self):
        self.assertEqual(module.check("python -S /etc/secrets/.render-ledger-bootstrap.py", "bash scripts/render_entrypoint.sh"), 1)

    def test_missing_actual_is_incomplete(self):
        self.assertEqual(module.check("  ", "bash scripts/render_entrypoint.sh"), 2)

    def test_extract_blueprint_command(self):
        self.assertEqual(module.blueprint_command("services:\n  - type: web\n    dockerCommand: bash scripts/render_entrypoint.sh\n"), "bash scripts/render_entrypoint.sh")

    def test_missing_blueprint_command_fails_closed(self):
        with self.assertRaises(ValueError):
            module.blueprint_command("services:\n  - type: web\n")

    def test_script_contains_no_execution_side_effects(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("subprocess.run(", "os.system(", "requests.post(", "create_order("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
