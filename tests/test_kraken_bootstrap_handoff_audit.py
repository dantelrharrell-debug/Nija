"""Offline regression for protected-bootstrap structural diagnostics.

Synthetic fixtures never contain credentials or production source code.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from scripts.audit_kraken_bootstrap_handoff import classify_source

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "audit_kraken_bootstrap_handoff.py"


def test_realistic_exec_handoff_without_registration_is_uncertified():
    status = classify_source("""
import os
def main():
    os.execvpe("bash", ["bash", "scripts/render_entrypoint.sh"], {})
main()
""")
    assert status["status"] == "process_replacement_requires_final_interpreter_registration"
    assert status["collector_certified"] is False
    assert status["orders_authorized"] is False


def test_registration_before_exec_cannot_be_treated_as_live_registration():
    status = classify_source("""
from bot.kraken_startup_receipts import register_signed_kraken_startup
import os
def main():
    register_signed_kraken_startup(factory, trust)
    os.execvpe("bash", ["bash", "scripts/render_entrypoint.sh"], {})
main()
""")
    assert status["status"] == "possible_registration_lost_at_process_replacement"
    assert status["collector_certified"] is False


def test_registration_reference_without_exec_is_still_not_certification():
    status = classify_source("""
from bot.kraken_canonical_startup_factory import register_canonical_kraken_collector_startup
register_canonical_kraken_collector_startup(
    trust=trust, resolve_sources=resolve_sources, review_sources=review_sources
)
""")
    assert status["status"] == "registration_visible_not_certified"
    assert status["orders_authorized"] is False


def test_bare_noop_bootstrap_must_not_certify():
    status = classify_source("print('hello')\n")
    assert status["status"] == "no_registration_visible"
    assert status["collector_certified"] is False


def test_cli_never_leaks_untrusted_source_and_never_returns_success(tmp_path):
    private = tmp_path / "private.py"
    private.write_text('raise RuntimeError("PRIVATE_FIXTURE_DO_NOT_EXPOSE")\n')
    finished = subprocess.run(
        [sys.executable, "-S", str(AUDIT), str(private)],
        capture_output=True, text=True, check=False,
    )
    assert finished.returncode == 2
    data = json.loads(finished.stdout)
    assert data["status"] == "no_registration_visible"
    assert data["orders_authorized"] is False
    assert "PRIVATE_FIXTURE_DO_NOT_EXPOSE" not in finished.stdout + finished.stderr


def test_invalid_private_file_returns_generic_denial(tmp_path):
    private = tmp_path / "private.py"
    private.write_text("PRIVATE_PARSE_FAILURE !!")
    finished = subprocess.run(
        [sys.executable, "-S", str(AUDIT), str(private)],
        capture_output=True, text=True, check=False,
    )
    assert finished.returncode == 2
    data = json.loads(finished.stdout)
    assert data["status"] == "audit_unavailable"
    assert "PRIVATE_PARSE_FAILURE" not in finished.stdout + finished.stderr
