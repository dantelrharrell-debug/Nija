"""Offline checks: never call Apollo, Render, Gmail or a brokerage."""
from __future__ import annotations

from scripts import nija_apollo_readonly_probe as probe


def test_probe_reports_expected_workspace_and_contact_count(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "local-private-token")
    responses = {
        "/auth/health": {"healthy": True, "is_logged_in": True},
        "/users/api_profile": {"team_id": "6a92e744cf82cd0010f5753c"},
        "/contacts/search": {"contacts": [{"id": "never-print-me"}], "pagination": {"total_entries": 314}},
    }
    monkeypatch.setattr(probe, "_safe_request", lambda path, **kw: responses[path])
    result = probe.check()
    assert result["status"] == "ok"
    assert result["saved_contacts_reported"] == 314
    assert result["profile"] == "expected_workspace"
    assert "local-private-token" not in str(result)
    assert "never-print-me" not in str(result)


def test_probe_identifies_other_workspace_without_disclosing_ids(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "another-private-token")
    responses = {
        "/auth/health": {"healthy": True, "is_logged_in": True},
        "/users/api_profile": {"team_id": "other-workspace-id"},
        "/contacts/search": {"contacts": [], "pagination": {"total_entries": 0}},
    }
    monkeypatch.setattr(probe, "_safe_request", lambda path, **kw: responses[path])
    result = probe.check()
    assert result["status"] == "requires_review"
    assert result["profile"] == "other_workspace"
    assert result["contacts_search"] == "zero_contacts"
    assert "other-workspace-id" not in str(result)
    assert "another-private-token" not in str(result)


def test_probe_missing_key_makes_no_request(monkeypatch):
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    monkeypatch.setattr(
        probe, "_safe_request",
        lambda *args, **kw: (_ for _ in ()).throw(AssertionError("must not access network")),
    )
    assert probe.check() == {"key_present": False, "status": "blocked_missing_key"}


def test_probe_scope_rejected_is_non_sensitive(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "sensitive-token")
    responses = {
        "/auth/health": {"healthy": True, "is_logged_in": True},
        "/users/api_profile": {"_error": "http_403"},
        "/contacts/search": {"_error": "http_403"},
    }
    monkeypatch.setattr(probe, "_safe_request", lambda path, **kw: responses[path])
    result = probe.check()
    assert result["profile"] == "http_403"
    assert result["contacts_search"] == "http_403"
    assert result["status"] == "requires_review"
    assert "sensitive-token" not in str(result)
