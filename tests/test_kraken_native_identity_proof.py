"""Offline signed transport fixtures, never real broker credentials or calls."""
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from requests import Request, Response, Session

from bot.kraken_authenticated_identity_v480 import (
    KrakenIdentityDenied, _fingerprint_iban, make_kraken_account_identity_provider,
)
from bot.kraken_identity_read_timing import query_identity_with_timing
from bot.kraken_native_identity_proof import ENDPOINT

PUBLIC = "offline-native-public-identifier"
SECRET = base64.b64encode(b"offline-native-signing-material").decode()
ACCOUNT = "OFFLINE ACCOUNT"


def rig(change=None, row=None):
    """Build a real requests response with a synthetic valid signed form."""
    calls = []
    api = SimpleNamespace(key=PUBLIC, secret=SECRET, response=None, session=Session())

    def query(method, params):
        calls.append((method, params))
        request = Request("POST", ENDPOINT, data={"nonce": "123456789"}).prepare()
        message = b"/0/private/GetApiKeyInfo" + hashlib.sha256(
            ("123456789" + request.body).encode(),
        ).digest()
        request.headers["API-Key"] = PUBLIC
        request.headers["API-Sign"] = base64.b64encode(hmac.new(
            base64.b64decode(SECRET), message, hashlib.sha512,
        ).digest()).decode()
        parsed = {"error": [], "result": {"iban": ACCOUNT} if row is None else row}
        response = Response()
        response.request = request
        response.url = ENDPOINT
        response.status_code = 200
        response._content_consumed = True
        response._content = json.dumps(parsed).encode()
        api.response = response
        if change:
            change(api, response, parsed)
        return parsed

    api.query_private = query
    broker = SimpleNamespace(api=api, connected=True, broker_type="kraken",
                             account_type="platform", user_id=None)
    broker._kraken_private_call = lambda endpoint, params, **_: query_identity_with_timing(api, params)
    return broker, calls


def provider(broker, **kwargs):
    """Select the alternative explicitly; existing callers retain strict mode."""
    return make_kraken_account_identity_provider(
        broker, account_scope="platform:kraken", approved_iban_sha256=_fingerprint_iban(ACCOUNT),
        approved_api_key_sha256=hashlib.sha256(PUBLIC.encode()).hexdigest(),
        reviewed_provider_id="offline-native-provider", monitoring_category=object(), **kwargs,
    )


def test_alternative_binds_signed_request_without_fabricating_response_fields():
    broker, calls = rig()
    observation = provider(broker, identity_method="native_signed_request_v1")()
    assert observation["verified"] is True
    assert observation["read_only"] is True
    assert "apiKey" not in broker.api.response.json()["result"]
    assert "validUntil" not in broker.api.response.json()["result"]
    assert all(value not in repr(observation) for value in (PUBLIC, SECRET, ACCOUNT))
    assert calls == [("GetApiKeyInfo", {})]
    assert "authorizes_orders" not in observation


def test_existing_default_still_denies_missing_echo():
    broker, _ = rig()
    with pytest.raises(KrakenIdentityDenied, match="authenticated_api_key_identity_missing"):
        provider(broker)()


@pytest.mark.parametrize("failure", [
    "signature", "request_key", "key_rotation", "secret_rotation", "wrong_account",
    "redirect", "endpoint", "status", "tls", "body", "nonce", "duplicate_nonce",
    "duplicate_json", "altered_parsed", "no_session", "session_swap", "old_response",
    "error", "noncanonical_body", "missing_signature",
])
def test_bad_native_binding_cannot_certify(failure):
    def change(api, response, parsed):
        request = response.request
        if failure == "signature":
            request.headers["API-Sign"] = "invalid"
        elif failure == "request_key":
            request.headers["API-Key"] = "different-offline-identifier"
        elif failure == "key_rotation":
            api.key = "different-offline-identifier"
        elif failure == "secret_rotation":
            api.secret = "changed"  # pragma: allowlist secret (offline negative fixture, no credential)
        elif failure == "wrong_account":
            parsed["result"]["iban"] = "OTHER ACCOUNT"
            response._content = json.dumps(parsed).encode()
        elif failure == "redirect":
            response.history = [Response()]
        elif failure == "endpoint":
            response.url = "https://example.invalid/"
        elif failure == "status":
            response.status_code = 500
        elif failure == "tls":
            api.session.verify = False
        elif failure == "body":
            request.body += "&otp=changed"
        elif failure == "nonce":
            request.body = "nonce=0"
        elif failure == "duplicate_nonce":
            request.body += "&nonce=123456789"
        elif failure == "duplicate_json":
            response._content = b'{"error":[],"result":{},"result":{}}'
        elif failure == "altered_parsed":
            parsed["result"]["permissions"] = []
        elif failure == "no_session":
            api.session = None
        elif failure == "session_swap":
            api.session = Session()
        elif failure == "old_response":
            api.response = None
        elif failure == "error":
            parsed["error"] = ["offline-private-error"]
            response._content = json.dumps(parsed).encode()
        elif failure == "noncanonical_body":
            request.body = "nonce=1&pair=XXBTZUSD"
        elif failure == "missing_signature":
            del request.headers["API-Sign"]
    broker, _ = rig(change)
    with pytest.raises(KrakenIdentityDenied):
        provider(broker, identity_method="native_signed_request_v1")()


@pytest.mark.parametrize("row", [
    {"iban": ACCOUNT, "validUntil": None}, {"iban": ACCOUNT, "validUntil": "1"},
    {"iban": ACCOUNT, "apiKey": None},  # pragma: allowlist secret (offline null fixture)
    {"iban": ACCOUNT, "apiKey": "wrong-identifier"},  # pragma: allowlist secret (offline negative fixture)
])
def test_present_bad_echo_or_expiry_is_never_ignored(row):
    broker, _ = rig(row=row)
    with pytest.raises(KrakenIdentityDenied):
        provider(broker, identity_method="native_signed_request_v1")()


def test_uninstrumented_gateway_cannot_select_native_proof():
    broker, _ = rig()
    broker._kraken_private_call = lambda *_, **__: {"error": [], "result": {"iban": ACCOUNT}}
    with pytest.raises(KrakenIdentityDenied, match="native_credential_binding_unverified"):
        provider(broker, identity_method="native_signed_request_v1")()


def permission_provider(broker, **kwargs):
    """Use independent account and credential pins for permission evidence."""
    from bot.kraken_authenticated_key_info_v477 import make_kraken_key_permission_provider
    return make_kraken_key_permission_provider(
        broker, account_scope="platform:kraken", approved_iban_sha256=_fingerprint_iban(ACCOUNT),
        approved_api_key_sha256=hashlib.sha256(PUBLIC.encode()).hexdigest(),
        reviewed_provider_id="offline-native-permission", monitoring_category=object(),
        identity_method="native_signed_request_v1", **kwargs,
    )


def permission_row():
    """Return a complete unrestricted read permission response, without echoes."""
    from bot.kraken_authenticated_key_info_v477 import REQUIRED_READ_PERMISSIONS
    return {"iban": ACCOUNT, "permissions": sorted(REQUIRED_READ_PERMISSIONS),
            "queryFrom": "0", "queryTo": "0"}


def test_native_permissions_require_genuine_signature_and_unrestricted_history():
    broker, calls = rig(row=permission_row())
    result = permission_provider(broker)()
    assert result["verified"] is True
    assert calls == [("GetApiKeyInfo", {})]
    assert all(value not in repr(result) for value in (PUBLIC, SECRET, ACCOUNT))


@pytest.mark.parametrize("field,value", [
    ("iban", "OTHER ACCOUNT"), ("permissions", ["query-funds"]),
    ("queryFrom", "1"), ("queryTo", "1"), ("queryFrom", None),
    ("validUntil", None), ("validUntil", "1"),
    ("apiKey", "wrong-identifier"),  # pragma: allowlist secret (offline negative fixture)
])
def test_native_permissions_keep_account_permissions_windows_and_present_fields_strict(field, value):
    from bot.kraken_authenticated_key_info_v477 import KeyInfoEvidenceDenied
    row = permission_row()
    row[field] = value
    broker, _ = rig(row=row)
    with pytest.raises(KeyInfoEvidenceDenied):
        permission_provider(broker)()


def ledger_identity(broker, tmp_path, **kwargs):
    """Exercise the ledger's real frozen transport wrapper without SQLite writes."""
    from bot.kraken_ledger_evidence import ReviewedLedgerBinding, _identity, _private_reader
    import time
    binding = ReviewedLedgerBinding(
        broker=broker, account="platform:kraken", provider_id="offline-native-ledger",
        api_key_sha256=hashlib.sha256(PUBLIC.encode()).hexdigest(),
        account_sha256=_fingerprint_iban(ACCOUNT), ledger_path=tmp_path / "absent.sqlite3",
        persistent_root=tmp_path, monitoring_category=object(),
        identity_method="native_signed_request_v1", **kwargs,
    )
    _identity(_private_reader(binding), binding, time.time())
    assert not binding.ledger_path.exists()


def test_native_ledger_identity_uses_the_same_actual_signature_proof(tmp_path):
    broker, calls = rig()
    ledger_identity(broker, tmp_path)
    assert calls == [("GetApiKeyInfo", {})]


@pytest.mark.parametrize("reader", ["permission", "ledger"])
@pytest.mark.parametrize("failure", ["signature", "wrong_account", "expiry", "echo", "gateway", "slow"])
def test_native_readers_cannot_accept_unproven_or_stale_identity(reader, failure, tmp_path, monkeypatch):
    import bot.kraken_identity_read_timing as timing
    from bot.kraken_authenticated_key_info_v477 import KeyInfoEvidenceDenied
    from bot.kraken_ledger_evidence import KrakenLedgerDenied
    row = permission_row()
    if failure == "expiry":
        row["validUntil"] = "1"
    if failure == "echo":
        row["apiKey"] = "wrong-identifier"  # pragma: allowlist secret (offline negative fixture)

    def change(api, response, parsed):
        if failure == "signature":
            response.request.headers["API-Sign"] = "invalid"
        if failure == "wrong_account":
            parsed["result"]["iban"] = "OTHER ACCOUNT"
            response._content = json.dumps(parsed).encode()
    broker, _ = rig(change, row=row)
    if failure == "gateway":
        broker._kraken_private_call = lambda *_, **__: {"error": [], "result": row}
    if failure == "slow":
        ticks = iter([100.0, 162.0, 162.0])
        monkeypatch.setattr(timing.time, "monotonic", lambda: next(ticks))
    with pytest.raises((KeyInfoEvidenceDenied, KrakenLedgerDenied)):
        if reader == "permission":
            permission_provider(broker)()
        else:
            ledger_identity(broker, tmp_path)
