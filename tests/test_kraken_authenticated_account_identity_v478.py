"""Offline, non-authorizing regressions for independently pinned Kraken IIBAN."""
import hashlib

import pytest

from bot.kraken_authenticated_account_identity_v478 import (
    AccountIdentityEvidenceDenied, make_kraken_account_identity_provider,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate

KEY = "test-only-public-key-id"
IIBAN = "AA08 N84G CPAR UN7A"
KEY_PIN = hashlib.sha256(KEY.encode()).hexdigest()
ACCOUNT_PIN = hashlib.sha256(("kraken\0" + IIBAN).encode()).hexdigest()
SCOPE = "platform:kraken"
PID = "reviewed-kraken-identity-provider"
CATEGORY = object()


class Broker:
    connected = True
    broker_type = "kraken"
    account_type = "platform"
    user_id = None

    def __init__(self):
        self.calls = []
        self.before_result = None
        self.reply = {"error": [], "result": {"apiKey": KEY, "iban": IIBAN}}

    def _kraken_private_call(self, endpoint, params, *, category):
        assert endpoint == "GetApiKeyInfo"
        assert params == {}
        assert category is CATEGORY
        self.calls.append(endpoint)
        if self.before_result:
            self.before_result()
        return self.reply


def build(broker, *, key_pin=KEY_PIN, account_pin=ACCOUNT_PIN,
          scope=SCOPE, stamps=(1000., 1001.)):
    ticks = iter(stamps)
    return make_kraken_account_identity_provider(
        broker, account_scope=scope, approved_api_key_sha256=key_pin,
        approved_account_iiban_sha256=account_pin,
        reviewed_provider_id=PID, monitoring_category=CATEGORY,
        clock=lambda: next(ticks),
    )


def test_one_authenticated_read_and_non_authorizing_evidence():
    broker = Broker()
    row = build(broker)()
    assert broker.calls == ["GetApiKeyInfo"]
    assert row["account"] == SCOPE and row["verified"] is True
    assert row["source"] == "authenticated_broker"
    assert row["observed_at_epoch"] == 1000.
    assert row["read_only"] is True
    assert KEY not in repr(row) and IIBAN not in repr(row)
    assert KEY_PIN not in repr(row) and ACCOUNT_PIN not in repr(row)
    assert "authorizes_orders" not in row
    ids = {field: "reviewed-" + field for field in REQUIRED}
    ids["account_identity"] = PID
    certificate = evaluate_pretrade_certificate(
        {"account_identity": row}, account=SCOPE,
        trusted_provider_ids=ids, now_epoch=1001.,
    )
    assert certificate["certified"] is False
    assert "broker_balances" in certificate["missing"]
    assert certificate["authorizes_orders"] is False


def test_pin_mismatch_rejected_without_leaking_key_or_iiban():
    for arg, code in (("key_pin", "reviewed_api_key_mismatch"),
                      ("account_pin", "reviewed_account_iiban_mismatch")):
        broker = Broker()
        with pytest.raises(AccountIdentityEvidenceDenied, match=code) as exc:
            build(broker, **{arg: "a" * 64})()
        assert KEY not in str(exc.value) and IIBAN not in str(exc.value)
        assert broker.calls == ["GetApiKeyInfo"]


def test_missing_reviewed_pins_rejected_before_broker_io():
    broker = Broker()
    with pytest.raises(AccountIdentityEvidenceDenied, match="api_key_reviewed_sha256_required"):
        build(broker, key_pin="not-reviewed")
    with pytest.raises(AccountIdentityEvidenceDenied, match="account_iiban_reviewed_sha256_required"):
        build(broker, account_pin="not-reviewed")
    assert not broker.calls


def test_missing_broker_iiban_rejected():
    broker = Broker()
    broker.reply["result"].pop("iban")
    with pytest.raises(AccountIdentityEvidenceDenied, match="authenticated_account_iiban_missing"):
        build(broker)()


def test_broker_scope_mismatch_rejected_before_io():
    broker = Broker()
    broker.account_type = "user"
    broker.user_id = "member-1"
    with pytest.raises(AccountIdentityEvidenceDenied, match="authenticated_broker_scope_unavailable"):
        build(broker)()
    assert not broker.calls


def test_member_scope_bound_exactly():
    broker = Broker()
    broker.account_type = "user"
    broker.user_id = "member-1"
    row = build(broker, scope="user:member-1:kraken")()
    assert row["account"] == "user:member-1:kraken"


def test_changed_scope_after_query_rejected():
    broker = Broker()
    broker.before_result = lambda: setattr(broker, "connected", False)
    with pytest.raises(AccountIdentityEvidenceDenied, match="broker_scope_changed"):
        build(broker)()


def test_private_api_error_is_safely_redacted():
    broker = Broker()
    broker.reply = {"error": ["sensitive-password-or-key"]}
    with pytest.raises(AccountIdentityEvidenceDenied, match="authenticated_identity_response_invalid") as exc:
        build(broker)()
    assert "password" not in str(exc.value)


def test_missing_api_key_rejected():
    broker = Broker()
    broker.reply["result"].pop("apiKey")
    with pytest.raises(AccountIdentityEvidenceDenied, match="authenticated_api_key_missing"):
        build(broker)()


def test_slow_query_rejected_by_started_at_timestamp():
    broker = Broker()
    with pytest.raises(AccountIdentityEvidenceDenied, match="observation_clock_invalid_or_stale"):
        build(broker, stamps=(1000., 1061.))()


def test_invalid_scope_and_provider_rejected_without_calls():
    broker = Broker()
    with pytest.raises(AccountIdentityEvidenceDenied, match="account_scope_invalid"):
        build(broker, scope="user:bad:scope:kraken")
    with pytest.raises(AccountIdentityEvidenceDenied, match="account_scope_invalid"):
        build(broker, scope="platform:okx")
    assert not broker.calls
