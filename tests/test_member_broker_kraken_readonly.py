"""Tests for isolated read-only Kraken authentication."""
import base64
import hashlib
import hmac
from urllib.parse import urlencode

import pytest

from member_broker_kraken_readonly import KrakenVerificationError, verify_kraken_readonly


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = {"error": [], "result": {"ZUSD": "0.0"}} if body is None else body
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.status, self.body)


def test_success_uses_only_readonly_balance_endpoint_and_valid_signature():
    session = FakeSession()
    key = base64.b64encode(b"test-secret").decode()
    assert verify_kraken_readonly("test-key", key, session=session, nonce=123456789) is True
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://api.kraken.com/0/private/Balance"
    assert kwargs["data"] == {"nonce": "123456789"}
    assert kwargs["allow_redirects"] is False
    digest = hashlib.sha256(("123456789" + urlencode({"nonce": "123456789"})).encode()).digest()
    expected = base64.b64encode(hmac.new(
        b"test-secret", b"/0/private/Balance" + digest, hashlib.sha512
    ).digest()).decode()
    assert kwargs["headers"] == {"API-Key": "test-key", "API-Sign": expected}


@pytest.mark.parametrize("status,body", [
    (403, {"error": [], "result": {}}),
    (200, {"error": ["EAPI:Invalid key"], "result": {}}),
    (200, {"error": [], "result": None}),
])
def test_failure_is_fail_closed(status, body):
    with pytest.raises(KrakenVerificationError, match="Kraken verification unavailable"):
        verify_kraken_readonly("test-key", base64.b64encode(b"test-secret").decode(),
                               session=FakeSession(status, body), nonce=123)


@pytest.mark.parametrize("secret", ["not base64!", "", " "])
def test_invalid_secret_never_calls_exchange(secret):
    session = FakeSession()
    with pytest.raises(KrakenVerificationError):
        verify_kraken_readonly("test-key", secret, session=session, nonce=123)
    assert session.calls == []
