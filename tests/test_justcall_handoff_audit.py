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
