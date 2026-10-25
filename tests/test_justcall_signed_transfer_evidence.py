"""Offline coverage: signed notifications cannot certify staffed handoffs."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest import mock
import hashlib
import hmac
import json
from urllib.parse import parse_qs, quote, urlsplit

import pytest

import render_justcall_handoff_audit as audit
import render_outreach_extension as extension
import render_outreach_store as store


@pytest.fixture
def signed_event(monkeypatch):
    monkeypatch.setenv("JUSTCALL_API_SECRET", "offline-fixture-only")
    monkeypatch.setattr(extension, "_webhook_url", lambda: "https://nija.example/api/justcall/webhook")
    payload = {"request_id": "offline-event", "type": "call.completed",
               "webhook_url": extension._webhook_url(), "data": {"id": "offline-call"}}

    def sign(body):
        timestamp = "2026-10-25 07:00:00"
        material = f"offline-fixture-only|{quote(body['webhook_url'], safe='')}|{body['type']}|{timestamp}"
        return {"x-justcall-signature": hmac.new(
            b"offline-fixture-only", material.encode(), hashlib.sha256).hexdigest(),
            "x-justcall-signature-version": "v1", "x-justcall-request-timestamp": timestamp}

    return payload, sign


def test_valid_v1_metadata_and_bad_mac(signed_event):
    payload, sign = signed_event
    headers = sign(payload)
    assert extension._signature_valid(SimpleNamespace(headers=headers), payload)
    headers["x-justcall-signature"] = "0" * 64
    assert not extension._signature_valid(SimpleNamespace(headers=headers), payload)


@pytest.mark.parametrize("version", [None, "", "v2"])
def test_signature_requires_explicit_supported_version(signed_event, version):
    payload, sign = signed_event
    headers = sign(payload)
    headers["x-justcall-signature-version"] = version
    assert not extension._signature_valid(SimpleNamespace(headers=headers), payload)


def test_even_valid_mac_for_other_endpoint_is_rejected(signed_event):
    payload, sign = signed_event
    payload["webhook_url"] = "https://other.example/api/justcall/webhook"
    assert not extension._signature_valid(SimpleNamespace(headers=sign(payload)), payload)


def test_provider_hmac_does_not_cover_body_or_request_id(signed_event):
    # Document the provider protocol limitation rather than claiming full-body
    # authentication. Only independent provider reads can corroborate outcomes.
    payload, sign = signed_event
    headers = sign(payload)
    payload["data"] = {"id": "different-call"}
    payload["request_id"] = "different-event"
    assert extension._signature_valid(SimpleNamespace(headers=headers), payload)


def test_bad_signature_has_no_persistence_or_suppression_side_effect(signed_event):
    payload, sign = signed_event
    raw = json.dumps(payload).encode()
    headers = {**sign(payload), "Content-Length": str(len(raw)), "x-justcall-signature": "0" * 64}
    handler = SimpleNamespace(path="/api/justcall/webhook", headers=headers, rfile=BytesIO(raw))
    with mock.patch.object(extension, "record_webhook_event") as persist, \
            mock.patch.object(extension, "_contact_status_suppression") as suppression, \
            mock.patch.object(extension, "_send_json") as respond:
        assert extension.handle_outreach_extension_post(handler)
    persist.assert_not_called()
    suppression.assert_not_called()
    assert respond.call_args.args[1] == 401


def _transfer_payload():
    return {"data": {"id": "call_123", "ai_agent_id": "agent_abc", "actions": [{
        "type": "call_transfer", "status": "success",
        "output": {"mode": "warm", "is_answered": True}}]}}


@pytest.mark.parametrize("failure", [{"success": False}, {"status": "failed"}, {"status": "error"}])
def test_failed_envelopes_cannot_supply_successful_transfer(failure):
    payload = _transfer_payload()
    assert not audit._answered_warm_transfer({**failure, **payload}, "agent_abc")
    payload["data"].update(failure)
    assert not audit._answered_warm_transfer(payload, "agent_abc")


@pytest.mark.parametrize("status,answered", [("failed", False), ("no_answer", False),
                                           ("busy", False), ("success", False), ("success", "true")])
def test_unanswered_or_nonboolean_answer_never_passes(status, answered):
    payload = _transfer_payload()
    payload["data"]["actions"][0]["status"] = status
    payload["data"]["actions"][0]["output"]["is_answered"] = answered
    assert not audit._answered_warm_transfer(payload, "agent_abc")


@pytest.mark.parametrize("returned_id", [None, "another-call", "call_123"])
def test_audit_binds_provider_evidence_to_requested_call(monkeypatch, returned_id):
    monkeypatch.setenv("JUSTCALL_AI_AGENT_ID", "agent_abc")
    monkeypatch.setenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED", "0")
    details = _transfer_payload()
    details["data"]["id"] = returned_id
    with mock.patch.object(audit, "_provider_request", side_effect=[
        {"data": [{"id": "call_123", "call_info": {"call_traits": ["Voice Agent"]}}]}, details,
    ]) as request:
        result = audit.audit_recent_handoff()
    assert result.get("provider_transfer_evidence", False) is (returned_id == "call_123")
    assert all(call.args[0] == "GET" for call in request.call_args_list)
    assert audit.os.getenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED") == "0"


def test_missed_and_voicemail_subscriptions_are_idempotent_and_nondialing(monkeypatch):
    monkeypatch.setattr(extension, "_webhook_url", lambda: "https://nija.example/webhook")
    subscriptions = {}

    def provider(method, path, *, payload=None):
        if method == "GET":
            event_type = parse_qs(urlsplit(path).query)["type"][0]
            return {"data": [subscriptions[event_type]] if event_type in subscriptions else []}
        assert method == "POST" and path == "/webhooks"
        subscriptions[payload["type"]] = deepcopy(payload)
        return {}

    with mock.patch.object(extension, "_justcall_webhook_request", side_effect=provider):
        added, _, failed = extension._ensure_justcall_webhooks_once()
        assert added == len(extension._AUTOCONFIG_EVENTS) and failed == 0
        assert {"call.missed", "call.voicemail"} <= subscriptions.keys()
        assert extension._ensure_justcall_webhooks_once() == (0, added, 0)


@pytest.mark.parametrize("event_type", ["call.missed", "call.voicemail"])
def test_no_answer_events_persist_idempotently_without_certification(monkeypatch, tmp_path, event_type):
    monkeypatch.setenv("NIJA_OUTREACH_DB_PATH", str(tmp_path / "outreach.sqlite3"))
    payload = {"request_id": "offline-missed", "type": event_type,
               "data": {"id": "offline-call", "call_info": {"disposition": "no_answer"}}}
    assert not store.record_webhook_event(payload)["duplicate"]
    assert store.record_webhook_event(payload)["duplicate"]
    row = store.recent_calls()[0]
    assert row["state"]["events"][event_type] == payload["data"]
    assert not audit._answered_warm_transfer({"data": row["state"]["derived"]}, "agent_abc")
