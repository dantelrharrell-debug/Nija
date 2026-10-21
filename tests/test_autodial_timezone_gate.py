"""Regression tests for fail-closed static autodial qualification.

These tests do not contact JustCall or enqueue live calls.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

import render_outreach_autodial as autodial


def _candidate(**overrides):
    record = {
        "record_id": "regression-contact",
        "contact_number": "+12065550123",
        "campaign": "NIJA Regression",
        "call_stage": "initial",
        "has_consent": True,
        "consent_record_id": "documented-consent-id",
        "legal_basis": "documented-review",
        "dnc_clear": True,
        "dnc_checked_at": datetime.now(timezone.utc).isoformat(),
        "suppression_clear": True,
        "campaign_enabled": True,
        "contact_timezone": "America/Los_Angeles",
    }
    record.update(overrides)
    return record


def test_timezone_is_required_for_static_readiness():
    ready, blocker = autodial._static_readiness(_candidate(contact_timezone=""))
    assert not ready
    assert "contact_timezone_required" in blocker


def test_invalid_timezone_fails_static_readiness():
    with pytest.raises(ValueError, match="valid IANA timezone"):
        autodial._static_readiness(_candidate(contact_timezone="Invalid/Zone"))


def test_valid_timezone_passes_static_readiness():
    ready, blocker = autodial._static_readiness(_candidate())
    assert ready
    assert blocker == ""


def test_consent_and_dnc_still_required_with_timezone():
    ready, blocker = autodial._static_readiness(
        _candidate(has_consent=False, dnc_clear=False)
    )
    assert not ready
    assert "verified_consent_required" in blocker
    assert "dnc_clear_required" in blocker


def test_invalid_timezone_is_rejected_before_enqueue():
    with pytest.raises(ValueError, match="valid IANA timezone"):
        autodial.enqueue_candidate(_candidate(contact_timezone="Invalid/Zone"))


def test_missing_timezone_stays_in_review_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("NIJA_OUTREACH_DB_PATH", str(tmp_path / "queue.sqlite3"))
    result = autodial.enqueue_candidate(_candidate(contact_timezone=""))
    assert result["queued"] is False
    assert result["state"] == "review_required"
    assert "contact_timezone_required" in result["blocker"]


def test_quarantine_existing_queued_record_missing_timezone(tmp_path, monkeypatch):
    monkeypatch.setenv("NIJA_OUTREACH_DB_PATH", str(tmp_path / "queue.sqlite3"))
    result = autodial.enqueue_candidate(_candidate())
    assert result["queued"] is True
    with autodial._connect() as connection:
        connection.execute(
            "UPDATE outreach_autodial_queue SET contact_timezone='' WHERE queue_key=?",
            (result["queue_key"],),
        )
        connection.commit()
    assert autodial._quarantine_static_nonready() == 1
    with autodial._connect() as connection:
        row = connection.execute(
            "SELECT state,last_blocker FROM outreach_autodial_queue WHERE queue_key=?",
            (result["queue_key"],),
        ).fetchone()
    assert row["state"] == "review_required"
    assert row["last_blocker"] == "contact_timezone_required"
