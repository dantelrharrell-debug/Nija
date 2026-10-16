"""Offline evidence reporter must never attest trading readiness."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch

from scripts import nija_offhost_ledger_evidence_report_v448 as reporter


def test_failed_verification_remains_fail_closed(capsys):
    with patch.object(reporter, "verify_snapshot", side_effect=ValueError("bad checksum")):
        status = reporter.main(["--archive", "/nonexistent/archive.tar.gz",
                                "--expected-sha256", "0" * 64])
    output = json.loads(capsys.readouterr().out)
    assert status == 1
    assert output["backup_restore_verified"] is False
    assert output["production_readiness_changed"] is False
    assert output["verification"] == "failed"


def test_success_never_certifies_custody_or_trading(capsys):
    with patch.object(reporter, "verify_snapshot", return_value={"sqlite_tables": {"trade_ledger": 3}}) as mock:
        status = reporter.main(["--archive", "/offline/archive.tar.gz",
                                "--expected-sha256", "a" * 64])
    output = json.loads(capsys.readouterr().out)
    assert status == 0
    mock.assert_called_once_with(Path("/offline/archive.tar.gz"),
                                 expected_sha256="a" * 64, exercise_restore=True)
    assert output["verification"] == "archive_integrity_and_isolated_restore_passed"
    assert output["backup_restore_verified"] is False
    assert output["off_host_custody_independently_established"] is False
    assert output["historical_reconciliation_verified"] is False
    assert output["production_readiness_changed"] is False
