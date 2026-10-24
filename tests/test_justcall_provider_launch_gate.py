"""Fail-closed JustCall provider approval regression; no calls or external APIs."""
from datetime import datetime, timezone
from unittest import mock

import render_outreach_autodial as dial


def test_missing_approval_prevents_worker_start_even_when_enabled():
    with mock.patch.dict("os.environ", {"NIJA_JUSTCALL_AUTODIAL_ENABLED": "1",
        "NIJA_JUSTCALL_PROVIDER_OUTBOUND_APPROVED": "0",
        "NIJA_JUSTCALL_PROVIDER_APPROVAL_REFERENCE": "",
        "NIJA_JUSTCALL_LIVE_CALLING_AUTHORIZED": "0"}, clear=False):
        assert not dial._worker_enabled()


def test_reference_is_not_sufficient_without_two_approvals():
    env = {"NIJA_JUSTCALL_AUTODIAL_ENABLED": "1",
           "NIJA_JUSTCALL_PROVIDER_OUTBOUND_APPROVED": "1",
           "NIJA_JUSTCALL_PROVIDER_APPROVAL_REFERENCE": "provider-case-ref",
           "NIJA_JUSTCALL_LIVE_CALLING_AUTHORIZED": "0"}
    with mock.patch.dict("os.environ", env):
        assert not dial._worker_enabled()


def test_all_explicit_approvals_required():
    env = {"NIJA_JUSTCALL_AUTODIAL_ENABLED": "1",
           "NIJA_JUSTCALL_PROVIDER_OUTBOUND_APPROVED": "1",
           "NIJA_JUSTCALL_PROVIDER_APPROVAL_REFERENCE": "provider-case-ref",
           "NIJA_JUSTCALL_LIVE_CALLING_AUTHORIZED": "1"}
    with mock.patch.dict("os.environ", env):
        assert dial._worker_enabled()
    env["NIJA_JUSTCALL_PROVIDER_APPROVAL_REFERENCE"] = " "
    with mock.patch.dict("os.environ", env):
        assert not dial._worker_enabled()


def test_provider_gate_rechecked_for_each_candidate():
    now = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)
    with mock.patch.object(dial, "_provider_launch_approved", return_value=False), \
         mock.patch.object(dial, "_quota_snapshot", return_value={"weekday_open": True, "remaining": 300}), \
         mock.patch.object(dial, "_weekend_call_eligibility", return_value=(False, "jurisdiction_required")), \
         mock.patch.object(dial, "_active_call_exists", return_value=False), \
         mock.patch.object(dial, "is_suppressed", return_value=False):
        row = {"has_consent": 0, "consent_record_id": "", "legal_basis": "",
               "dnc_clear": 0, "dnc_checked_at": "", "suppression_clear": 0,
               "contact_number": "+12065550123", "campaign_enabled": 0,
               "weekend_evidence_json": "{}", "campaign": "NIJA QA"}
        blockers, _ = dial._eligibility(row, now)
        assert "provider_outbound_approval_required" in blockers


def test_no_launch_approval_without_explicit_environment_values():
    with mock.patch.dict("os.environ", {
        "NIJA_JUSTCALL_AUTODIAL_ENABLED": "1",
        "NIJA_JUSTCALL_PROVIDER_OUTBOUND_APPROVED": "",
        "NIJA_JUSTCALL_PROVIDER_APPROVAL_REFERENCE": "",
        "NIJA_JUSTCALL_LIVE_CALLING_AUTHORIZED": "",
    }):
        assert not dial._provider_launch_approved()
        assert not dial._worker_enabled()
