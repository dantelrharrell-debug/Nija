"""Offline Kraken cursor transport test: no secrets, no network, no trading.

Verify the actual krakenex 2.2.2 and requests POST form serialization; do not
claim that an observed capitalization difference proves Kraken's rejection.
"""
import base64
import json
from urllib.parse import parse_qs, urlencode

import krakenex
import requests


class _OfflineResponse:
    status_code = 200

    def json(self, **_kwargs):
        return {"error": [], "result": {"cursor": {}, "open": {}, "trades": {}}}


def _capture_private_form(endpoint, params):
    """Use krakenex's real signing/path code but intercept POST before network."""
    captured = []
    api = krakenex.API(
        key="offline-fixture-only",
        secret=base64.b64encode(b"not-a-real-kraken-secret").decode("ascii"),
    )
    api._nonce = lambda: 1234567890

    def blocked_post(url, data=None, headers=None, timeout=None):
        assert url == "https://api.kraken.com/0/private/" + endpoint
        prepared = requests.Request("POST", url, data=data, headers=headers).prepare()
        assert prepared.headers["API-Sign"] == api._sign(
            data, "/0/private/" + endpoint
        )
        captured.append((dict(data), str(prepared.body)))
        return _OfflineResponse()

    api.session.post = blocked_post
    try:
        output = api.query_private(endpoint, dict(params))
    finally:
        api.close()
    assert output["error"] == []
    assert len(captured) == 1
    return captured[0]


def test_actual_krakenex_form_encoder_uppercases_python_boolean_cursor_flags():
    for endpoint, fields in (
        ("TradesHistory", {"with_cursor": True}),
        ("OpenOrders", {"with_cursor": True, "trades": True, "limit": 50}),
    ):
        values, body = _capture_private_form(endpoint, fields)
        decoded = parse_qs(body, keep_blank_values=True)
        assert decoded["with_cursor"] == ["True"]
        assert values["with_cursor"] is True
        assert decoded["nonce"] == ["1234567890"]
        assert "with_cursor=True" in body
        if endpoint == "OpenOrders":
            assert decoded["trades"] == ["True"]
        assert "nonce=" in body


def test_lowercase_boolean_strings_are_signed_and_sent_identically_without_network():
    for endpoint, fields in (
        ("TradesHistory", {"with_cursor": "true"}),
        ("OpenOrders", {"with_cursor": "true", "trades": "true", "limit": 50}),
    ):
        values, body = _capture_private_form(endpoint, fields)
        decoded = parse_qs(body, keep_blank_values=True)
        assert decoded["with_cursor"] == ["true"]
        assert values["with_cursor"] == "true"
        if endpoint == "OpenOrders":
            assert decoded["trades"] == ["true"]


def test_python_json_booleans_and_form_booleans_have_different_wire_text():
    request = {"with_cursor": True, "trades": False}
    as_json = json.dumps(request)
    as_form = urlencode(request)
    assert '"with_cursor": true' in as_json
    assert '"trades": false' in as_json
    assert "with_cursor=True" in as_form
    assert "trades=False" in as_form
