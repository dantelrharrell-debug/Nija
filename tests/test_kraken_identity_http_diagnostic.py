"""Offline HTTP-versus-parsed field diagnostics; no exchange or order calls."""
import hashlib
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from requests import Request, Response

from bot import kraken_identity_read_timing as timing
from bot import kraken_identity_request_recovery_v491 as recovery
from bot.kraken_authenticated_identity_v480 import (
    KrakenIdentityDenied, _fingerprint_iban, make_kraken_account_identity_provider,
)

ENDPOINT = "https://api.kraken.com/0/private/GetApiKeyInfo"
KEY = "fixture-only-key"
ACCOUNT = "fixture-only-account"


def http_response(body=None):
    response = Response()
    response.status_code = 200
    response.url = ENDPOINT
    response.request = Request("POST", ENDPOINT).prepare()
    response._content = json.dumps(body if body is not None else {
        "error": [], "result": {"apiKey": KEY, "iban": ACCOUNT, "validUntil": "0"},
    }).encode()
    response._content_consumed = True
    return response


@pytest.mark.parametrize("failure", [
    "stale", "foreign_type", "wrong_host", "wrong_path", "redirect", "status",
    "get", "wrong_request_url", "missing_request", "oversized", "invalid_json",
    "duplicate_root", "duplicate_field", "api_error", "wrong_result", "streaming",
])
def test_unbound_or_ambiguous_http_has_no_diagnostic(failure):
    response = http_response()
    previous = None
    if failure == "stale":
        previous = response
    elif failure == "foreign_type":
        response = SimpleNamespace(**response.__dict__)
    elif failure == "wrong_host":
        response.url = ENDPOINT.replace("api.kraken.com", "example.invalid")
    elif failure == "wrong_path":
        response.url = ENDPOINT.replace("GetApiKeyInfo", "Balance")
    elif failure == "redirect":
        response.history = [http_response()]
    elif failure == "status":
        response.status_code = 500
    elif failure == "get":
        response.request.method = "GET"
    elif failure == "wrong_request_url":
        response.request.url = ENDPOINT + "?unverified=1"
    elif failure == "missing_request":
        response.request = None
    elif failure == "oversized":
        response._content = b" " * 65537
    elif failure == "invalid_json":
        response._content = b"not JSON"
    elif failure == "duplicate_root":
        response._content = b'{"error":[],"result":{},"result":{}}'
    elif failure == "duplicate_field":
        response._content = b'{"error":[],"result":{"validUntil":0,"validUntil":1}}'
    elif failure == "api_error":
        response._content = b'{"error":["private fixture error"],"result":{}}'
    elif failure == "wrong_result":
        response._content = b'{"error":[],"result":[]}'
    elif failure == "streaming":
        response._content = False
        response._content_consumed = False
    assert timing._http_field_presence(SimpleNamespace(response=response), previous) is None


def fixture_broker(http_has_fields=True, parsed_has_fields=False):
    api = SimpleNamespace(response=None)
    calls = []

    def query(method, params):
        calls.append((method, dict(params)))
        wire = {"error": [], "result": {"iban": ACCOUNT}}
        if http_has_fields:
            wire["result"].update({"apiKey": KEY, "validUntil": "0"})
        api.response = http_response(wire)
        if parsed_has_fields:
            return wire
        # Reproduce the observed incomplete parsed reply without changing wire data.
        return {"error": [], "result": {"iban": ACCOUNT}}

    api.query_private = query
    broker = SimpleNamespace(
        api=api, connected=True, broker_type="kraken", account_type="platform", user_id=None,
    )

    def read(method, params, *, category):
        assert method == "GetApiKeyInfo"
        return timing.query_identity_with_timing(api, params)

    broker._kraken_private_call = read
    return broker, calls


@pytest.mark.parametrize("wire_has_fields", [False, True])
def test_http_presence_never_repairs_missing_parsed_identity(wire_has_fields):
    broker, calls = fixture_broker(wire_has_fields)
    observed = []
    provider = make_kraken_account_identity_provider(
        broker, account_scope="platform:kraken",
        approved_api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
        approved_iban_sha256=_fingerprint_iban(ACCOUNT),
        reviewed_provider_id="offline-fixture", monitoring_category=object(),
        http_field_observer=observed.append,
    )
    with pytest.raises(KrakenIdentityDenied, match="authenticated_api_key_identity_missing"):
        provider()
    assert observed == [{field: wire_has_fields for field in ("apiKey", "validUntil")}]
    assert calls == [("GetApiKeyInfo", {})]
    assert KEY not in json.dumps(observed) and ACCOUNT not in json.dumps(observed)


def test_diagnostic_delivery_failure_does_not_change_identity_decision():
    broker, calls = fixture_broker(parsed_has_fields=True)

    def reject_diagnostic(fields):
        raise RuntimeError("fixture-only private diagnostic error")

    provider = make_kraken_account_identity_provider(
        broker, account_scope="platform:kraken",
        approved_api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
        approved_iban_sha256=_fingerprint_iban(ACCOUNT),
        reviewed_provider_id="offline-fixture", monitoring_category=object(),
        http_field_observer=reject_diagnostic,
    )
    assert provider()["verified"] is True
    assert calls == [("GetApiKeyInfo", {})]


def test_unrequested_diagnostic_does_not_read_http_body():
    class API:
        @property
        def response(self):
            raise AssertionError("unrequested HTTP inspection")

        def query_private(self, method, params):
            return {"error": [], "result": {}}

    api = API()
    with timing.capture_identity_read(api, time.time) as capture:
        timing.query_identity_with_timing(api, {})
    assert capture.http_field_presence is None


def test_failed_one_shot_receipt_records_only_boolean_http_presence(tmp_path):
    tmp_path.chmod(0o700)
    binding = {
        "account_scope": "platform:kraken", "approval_source": "offline-fixture-only",
        "approved_account_iiban_sha256": _fingerprint_iban(ACCOUNT),
        "approved_api_key_sha256": hashlib.sha256(KEY.encode()).hexdigest(),
        "approved_at_utc": datetime.fromtimestamp(
            time.time() - 5, timezone.utc,
        ).isoformat(),
        "authenticated_identity_match_verified": False,
        "independent_statement_reference": "offline-fixture-only",
        "runtime_collector_installed": False, "trading_authorized": False,
    }
    request = {"request_id": "a" * 32, "account_scope": "platform:kraken",
               "max_pages": 1, "created_at": time.time() - 1}
    for name, value in ((recovery.BINDING_NAME, binding), ("identity_request.json", request)):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    broker, calls = fixture_broker()
    assert recovery.collect_requested_identity(tmp_path, [broker], monitoring_category=object())
    receipt = json.loads((tmp_path / ("a" * 32 + ".identity.evidence.json")).read_text())
    assert receipt["http_identity_field_presence"] == {field: True for field in ("apiKey", "validUntil")}
    assert receipt["parsed_identity_field_presence"] == {field: False for field in ("apiKey", "validUntil")}
    assert receipt["failure_code"] == "authenticated_api_key_identity_missing"
    for field in ("collection_succeeded", "collector_installed", "trading_authorized"):
        assert receipt[field] is False
    assert KEY not in json.dumps(receipt) and ACCOUNT not in json.dumps(receipt)
    assert not recovery.collect_requested_identity(tmp_path, [broker], monitoring_category=object())
    assert calls == [("GetApiKeyInfo", {})]
