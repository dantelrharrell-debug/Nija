"""Offline tests for JustCall provider-history audit log safety. No provider traffic."""
from __future__ import annotations

from unittest import mock

import render_justcall_provider_audit as audit
import render_outreach_autodial as dial


def test_verified_history_prints_provider_totals_without_identifiers(capsys):
    result = {
        "verified": True,
        "date": "2026-10-14",
        "confirmed_outbound_attempts": 12,
        "sources": {
            "justcall": {"matched_outbound_ids": 10},
            "sales_dialer": {"matched_outbound_ids": 2},
        },
    }
    with mock.patch.object(audit, "audit_provider_today", return_value=result):
        returned = audit.run_readonly_provider_history_audit()
    line = capsys.readouterr().out
    assert returned is result
    assert "state=verified" in line
    assert "confirmed=12" in line
    assert "gap=288" in line
    assert "justcall=10" in line
    assert "sales_dialer=2" in line
    assert "source=provider_api" in line


def test_unverified_history_does_not_claim_zero(capsys):
    result = {
        "verified": False,
        "reason": "provider_api_error_http_403",
        "blocked_source": "sales_dialer",
    }
    with mock.patch.object(audit, "audit_provider_today", return_value=result):
        audit.run_readonly_provider_history_audit()
    line = capsys.readouterr().out
    assert "state=unverified" in line
    assert "confirmed=unverified" in line
    assert "gap=unverified" in line
    assert "reason=provider_api_error_http_403" in line


def test_injected_provider_response_not_logged(capsys):
    private_marker = "private5551212"
    result = {
        "verified": False,
        "reason": "error_\n" + private_marker,
        "blocked_source": "justcall\n" + private_marker,
    }
    with mock.patch.object(audit, "audit_provider_today", return_value=result):
        audit.run_readonly_provider_history_audit()
    line = capsys.readouterr().out
    assert private_marker not in line
    assert "confirmed=unverified" in line


def test_provider_exception_does_not_expose_error_message(capsys):
    private_marker = "private5551212"
    with mock.patch.object(audit, "audit_provider_today",
                           side_effect=RuntimeError(private_marker)):
        audit.run_readonly_provider_history_audit()
    line = capsys.readouterr().out
    assert private_marker not in line
    assert "unexpected_runtimeerror" in line
    assert "confirmed=unverified" in line


def test_poll_interval_is_bounded(monkeypatch):
    monkeypatch.setenv("NIJA_JUSTCALL_HISTORY_POLL_SECONDS", "1")
    assert audit._history_poll_seconds() == 900
    monkeypatch.setenv("NIJA_JUSTCALL_HISTORY_POLL_SECONDS", "9999999")
    assert audit._history_poll_seconds() == 86400
    monkeypatch.setenv("NIJA_JUSTCALL_HISTORY_POLL_SECONDS", "bad")
    assert audit._history_poll_seconds() == 3600


def test_auditor_boot_is_idempotent_without_running_threads():
    fake_thread = mock.Mock()
    with mock.patch.object(audit.threading, "Thread", return_value=fake_thread):
        with mock.patch.object(audit, "_AUDIT_WORKER_STARTED", False):
            audit.start_readonly_provider_history_audit()
            audit.start_readonly_provider_history_audit()
    fake_thread.start.assert_called_once()


def test_autodial_boot_starts_read_only_poll_even_if_worker_disabled():
    mock_thread = mock.Mock()
    with mock.patch.object(dial.threading, "Thread", return_value=mock_thread):
        with mock.patch.object(dial, "_WORKER_STARTED", False):
            with mock.patch.object(audit, "start_readonly_provider_history_audit") as start:
                dial.start_justcall_autodial()
    start.assert_called_once()
    mock_thread.start.assert_called_once()
