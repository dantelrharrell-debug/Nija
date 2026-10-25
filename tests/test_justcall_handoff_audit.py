"""Offline regression coverage for the read-only JustCall handoff audit."""
from unittest import mock

import render_justcall_handoff_audit as audit


def test_answered_warm_transfer_requires_agent_success_mode_and_answer():
    payload = {"data": {"ai_agent_id": "agent_abc", "actions": [{
        "type": "call_transfer", "status": "success",
        "output": {"mode": "warm", "is_answered": True}
    }]}}
    assert audit._answered_warm_transfer(payload, "agent_abc") is True
    assert audit._answered_warm_transfer(payload, "agent_other") is False
    for change in (
        {"status": "failed"},
        {"output": {"mode": "cold", "is_answered": True}},
        {"output": {"mode": "warm", "is_answered": False}},
    ):
        action = {**payload["data"]["actions"][0], **change}
        assert audit._answered_warm_transfer(
            {"data": {"ai_agent_id": "agent_abc", "actions": [action]}},
            "agent_abc",
        ) is False


def test_missing_or_unexpected_payload_fails_closed():
    assert audit._answered_warm_transfer({"data": {}}, "agent_abc") is False
    assert audit._answered_warm_transfer({"data": {"actions": []}}, "agent_abc") is False


def test_audit_does_not_submit_calls_or_enable_handoff(monkeypatch):
    monkeypatch.setenv("JUSTCALL_AI_AGENT_ID", "agent_abc")
    monkeypatch.setenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED", "0")
    with mock.patch.object(audit, "_provider_request", return_value={"data": []}) as request:
        result = audit.audit_recent_handoff()
    assert result["state"] == "unverified"
    assert all(call.args[0] == "GET" for call in request.call_args_list)
    assert audit.os.getenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED") == "0"


def test_candidate_requires_voice_agent_or_transfer_trait():
    assert audit._candidate({"call_info": {"call_traits": ["Voice Agent"]}})
    assert audit._candidate({"call_info": {"call_traits": ["Transfer"]}})
    assert not audit._candidate({"call_info": {"call_traits": ["Outbound"]}})
    assert not audit._candidate({"call_info": {}})


def test_hourly_worker_survives_unexpected_audit_error(monkeypatch):
    events = []
    def failing_audit():
        events.append("audit")
        raise RuntimeError("unexpected provider response containing private data")
    def stop_after_first_cycle(seconds):
        events.append(("sleep", seconds))
        raise KeyboardInterrupt()
    monkeypatch.setattr(audit, "run_readonly_handoff_audit", failing_audit)
    monkeypatch.setattr(audit.time, "sleep", stop_after_first_cycle)
    with mock.patch("builtins.print") as log:
        try:
            audit._handoff_worker()
        except KeyboardInterrupt:
            pass
    assert events == ["audit", ("sleep", 3600)]
    message = " ".join(str(part) for call in log.call_args_list for part in call.args)
    assert "state=worker_error" in message
    assert "RuntimeError" in message
    assert "private data" not in message


def test_provider_shape_rejects_malformed_or_failed_response():
    import pytest
    with pytest.raises(ValueError):
        audit._call_rows({"data": {"calls": [None]}})
    with pytest.raises(ValueError):
        audit._call_rows({"success": False, "data": []})
    with pytest.raises(ValueError):
        audit._call_rows({"data": {"unexpected": []}})


def test_provider_transfer_evidence_does_not_attest_human_identity(monkeypatch):
    monkeypatch.setenv("JUSTCALL_AI_AGENT_ID", "agent_abc")
    monkeypatch.setenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED", "0")
    def fake_get(method, path, **kwargs):
        assert method == "GET"
        if path.startswith("/calls?"):
            return {"data": [{"id": "call_123", "call_info": {"call_traits": ["Voice Agent"]}}]}
        if path == "/calls/call_123/voice-agent":
            return {"data": {"id": "call_123", "ai_agent_id": "agent_abc", "actions": [{
                "type": "call_transfer", "status": "success",
                "output": {"mode": "warm", "is_answered": True}
            }]}}
        raise AssertionError("unexpected provider path")
    monkeypatch.setattr(audit, "_provider_request", fake_get)
    result = audit.audit_recent_handoff()
    assert result["state"] == "answered_warm_transfer"
    assert result["provider_transfer_evidence"] is True
    assert result["human_identity_independently_verified"] is False
    assert audit.os.getenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED") == "0"


def test_malformed_selected_agent_id_fails_closed_without_provider_call(monkeypatch):
    monkeypatch.setenv("JUSTCALL_AI_AGENT_ID", "agent_abc/../../unsafe")
    with mock.patch.object(audit, "_provider_request") as provider:
        result = audit.audit_recent_handoff()
    assert result["state"] == "unverified"
    assert result["reason"] == "selected_agent_id_missing_or_invalid"
    provider.assert_not_called()
