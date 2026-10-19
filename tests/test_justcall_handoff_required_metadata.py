"""Regression tests for mandatory JustCall human-handoff reporting.

The retired NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF switch must never claim
handoff is optional. Tests use an offline temp database and make no calls.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

import render_outreach_autodial as dial


def test_status_reports_mandatory_handoff_even_with_legacy_override(tmp_path):
    with mock.patch.dict(os.environ, {
        "NIJA_OUTREACH_DB_PATH": str(tmp_path / "outreach.sqlite3"),
        "NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF": "0",
        "NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED": "0",
    }):
        state = dial._queue_status()
    assert state["human_handoff_required"] is True
    assert state["human_handoff_verified"] is False
    assert state["fail_closed"] is True


def test_worker_startup_cannot_report_handoff_optional(capsys):
    with (
        mock.patch.dict(os.environ, {
            "NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF": "0",
            "NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED": "0",
        }),
        mock.patch.object(dial, "_worker_enabled", return_value=True),
        mock.patch.object(dial, "_quarantine_static_nonready", return_value=0),
        mock.patch.object(dial, "_run_cycle", return_value=(0, 0)),
        mock.patch.object(dial.time, "sleep", side_effect=KeyboardInterrupt),
    ):
        with pytest.raises(KeyboardInterrupt):
            dial._worker()
    log = capsys.readouterr().out
    assert "state=ready" in log
    assert "human_handoff_required=true" in log
    assert "human_handoff_required=false" not in log
    assert "fail_closed=true" in log
