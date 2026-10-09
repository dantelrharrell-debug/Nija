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
