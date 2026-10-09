"""Regression: legacy campaign endpoint cannot bypass the vetted JustCall queue."""
from __future__ import annotations
from io import BytesIO
from unittest import mock
import render_outreach_extension as extension

class FakeHandler:
    path = "/api/justcall/campaign-calls"
    def __init__(self):
        self.headers = {"X-NIJA-Outreach-Token": "internal-test"}
        self.rfile = BytesIO(b"")

def test_legacy_campaign_call_fails_closed_even_with_claimed_consent():
    handler = FakeHandler()
    with (
        mock.patch.object(extension, "_service_authorized", return_value=(True, 200, "ok")),
        mock.patch.object(extension, "_send_json") as send,
        mock.patch.object(extension, "_provider_request") as provider,
    ):
        assert extension.handle_outreach_extension_post(handler) is True
        assert send.call_args.args[1] == 409
        provider.assert_not_called()

def test_legacy_campaign_call_denies_unauthorized_user():
    handler = FakeHandler()
    with (
        mock.patch.object(extension, "_service_authorized", return_value=(False, 401, "Unauthorized")),
        mock.patch.object(extension, "_send_json") as send,
        mock.patch.object(extension, "_provider_request") as provider,
    ):
        assert extension.handle_outreach_extension_post(handler) is True
        assert send.call_args.args[1] == 401
        provider.assert_not_called()

def test_agent_inventory_read_only_does_not_verify_transfer():
    payload = {"data": {"agents": [{
        "id": "agent_test123",
        "actions": [{"type": "transfer_call", "transfer_type": "warm"}],
    }]}}
    result = extension._agent_inventory_summary(payload, "agent_test123")
    assert result["agent_count"] == 1
    assert result["selected_agent_identified"] is True
    assert result["warm_transfer_action_listed"] is True
    assert result["human_handoff_verified"] is False

def test_missing_agent_metadata_never_promotes_transfer_to_verified():
    result = extension._agent_inventory_summary({"data": {}}, "")
    assert result["agent_count"] == 0
    assert result["human_handoff_verified"] is False

def test_provider_inventory_audit_never_submits_a_call():
    with (
        mock.patch.object(extension, "_justcall_webhook_request", return_value={
            "data": {"agents": [{"id": "agent_demo"}]}
        }) as provider,
        mock.patch.object(extension, "_provider_request") as outbound,
        mock.patch("builtins.print"),
    ):
        extension._audit_justcall_agents_readonly()
        assert provider.call_args.args[0] == "GET"
        outbound.assert_not_called()
