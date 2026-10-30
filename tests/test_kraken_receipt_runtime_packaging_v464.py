"""Regression: the private, read-only Kraken failure triage CLI must ship in Render.

These tests do not connect to Kraken, SSH, or the production data directory.
The real Docker image build verifies that the tool also exists in /app/scripts.
"""
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "nija_kraken_failure_receipt_triage_v464.py"


def test_private_failed_receipt_triage_explicitly_allowed_in_docker_context():
    patterns = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "scripts/*" in patterns
    assert "!scripts/nija_kraken_failure_receipt_triage_v464.py" in patterns
    assert SCRIPT.is_file()


def test_render_image_refuses_to_build_without_private_triage_script():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "/app/scripts/nija_kraken_failure_receipt_triage_v464.py \\" in dockerfile
    assert "test -s /app/scripts/nija_kraken_failure_receipt_triage_v464.py" in dockerfile


def test_packaged_triage_command_is_standalone_and_has_no_broker_side_effects():
    completed = subprocess.run(
        [sys.executable, "-B", "-S", str(SCRIPT), "--help"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=10, check=False,
    )
    assert completed.returncode == 0
    assert "--recovery-dir" in completed.stdout
    assert "--request-id" in completed.stdout
