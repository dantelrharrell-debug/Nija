"""Trial admission must fail closed before creating a Stripe checkout."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import member_broker_availability as availability


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"status": "ready", "credential_intake_enabled": True, "verification_enabled": True}, True),
    (503, {"status": "not_ready"}, False),
    (302, {"status": "ready"}, False),
    (200, {"status": "ready", "credential_intake_enabled": True}, False),
    (200, {"status": "ready", "credential_intake_enabled": False, "verification_enabled": True}, False),
    (200, {"status": "ready", "credential_intake_enabled": "true", "verification_enabled": True}, False),
    (200, [], False),
])
def test_public_capabilities_are_strict(monkeypatch, status, payload, expected):
    transport = Mock(return_value=SimpleNamespace(status_code=status, json=lambda: payload))
    monkeypatch.setattr(availability.requests, "get", transport)
    assert availability.member_broker_setup_available() is expected
    transport.assert_called_once_with(
        availability.READINESS_URL, timeout=3.0, allow_redirects=False,
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
    )


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError(), ValueError()])
def test_transport_or_json_failure_denies_trial(monkeypatch, failure):
    monkeypatch.setattr(availability.requests, "get", Mock(side_effect=failure))
    assert availability.member_broker_setup_available() is False
