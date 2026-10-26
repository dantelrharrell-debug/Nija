"""Synthetic, offline, non-authorizing Kraken key information regressions."""
import hashlib

import pytest

from bot.kraken_authenticated_key_info_v477 import (
    KeyInfoEvidenceDenied, make_kraken_key_permission_provider,
)
from bot.pretrade_attestation_validation_v452 import (
    REQUIRED, evaluate_pretrade_certificate,
)

KEY = "unused-synthetic-kraken-public-key-id"
FINGERPRINT = hashlib.sha256(KEY.encode()).hexdigest()
SCOPE = "platform:kraken"
CATEGORY = object()
PROVIDER_ID = "reviewed-kraken-broker-001"


class Broker:
    connected = True
    broker_type = "kraken"
    account_type = "platform"
    user_id = None

    def __init__(self):
        self.calls = []
        self.reply = {"error": [], "result": {
            "apiKey": KEY,
            "permissions": ["query-funds", "query-open-trades", "query-closed-trades", "query-ledger"],
            "validUntil": "0", "queryFrom": "0", "queryTo": "0",
        }}
        self.before_result = None

    def _kraken_private_call(self, endpoint, params, *, category):
        assert endpoint == "GetApiKeyInfo"
        assert params == {}
        assert category is CATEGORY
        self.calls.append(endpoint)
        if self.before_result:
            self.before_result()
        return self.reply


def build(broker, *, fingerprint=FINGERPRINT, scope=SCOPE, now=None):
    tick = iter(now if now is not None else [1000.0, 1001.0])
    return make_kraken_key_permission_provider(
        broker, account_scope=scope, approved_api_key_sha256=fingerprint,
        reviewed_provider_id=PROVIDER_ID, monitoring_category=CATEGORY,
        clock=lambda: next(tick),
    )


def test_authentic_pinned_key_has_one_non_authorizing_permissions_observation():
    broker = Broker()
    row = build(broker)()
    assert broker.calls == ["GetApiKeyInfo"]
    assert row["verified"] is True
    assert row["source"] == "authenticated_broker"
    assert row["account"] == SCOPE
    assert row["observed_at_epoch"] == 1000.0
    assert KEY not in str(row)
    assert FINGERPRINT not in str(row)
    assert "authorizes_orders" not in row
    # One verified permissions field is not a full v452 pretrade certificate.
    ids = {field: "reviewed-" + field for field in REQUIRED}
    ids["account_permissions"] = PROVIDER_ID
    result = evaluate_pretrade_certificate(
        {"account_permissions": row}, account=SCOPE,
        trusted_provider_ids=ids, now_epoch=1001.0,
    )
    assert result["certified"] is False
    assert "account_identity" in result["missing"]
    assert result["authorizes_orders"] is False


def test_wrong_fingerprint_fails_closed_without_returning_key():
    broker = Broker()
    with pytest.raises(KeyInfoEvidenceDenied, match="fingerprint_mismatch") as exc:
        build(broker, fingerprint="a"*64)()
    assert KEY not in str(exc.value)
    assert len(broker.calls) == 1


def test_invalid_or_missing_expected_fingerprint_rejected_before_io():
    broker = Broker()
    with pytest.raises(KeyInfoEvidenceDenied, match="reviewed_key_fingerprint_required"):
        build(broker, fingerprint="unverified")
    assert not broker.calls


def test_disconnected_and_ambiguous_scope_denied_before_io():
    broker = Broker()
    broker.connected = False
    with pytest.raises(KeyInfoEvidenceDenied, match="authenticated_client_unavailable"):
        build(broker)()
    assert not broker.calls
    broker.connected = True
    broker.account_type = "user"
    broker.user_id = "another-member"
    with pytest.raises(KeyInfoEvidenceDenied, match="broker_scope_mismatch"):
        build(broker)()
    assert not broker.calls


def test_broker_scope_change_after_authenticated_read_rejected():
    broker = Broker()
    broker.before_result = lambda: setattr(broker, "connected", False)
    with pytest.raises(KeyInfoEvidenceDenied, match="broker_scope_changed"):
        build(broker)()


def test_history_restrictions_deny_completeness():
    for field in ("queryFrom", "queryTo"):
        broker = Broker()
        broker.reply["result"][field] = "1792000000"
        with pytest.raises(KeyInfoEvidenceDenied, match="historical_query_window_restricted"):
            build(broker)()


def test_missing_required_permission_rejected():
    broker = Broker()
    broker.reply["result"]["permissions"].remove("query-ledger")
    with pytest.raises(KeyInfoEvidenceDenied, match="required_read_permissions_missing"):
        build(broker)()


def test_key_expired_rejected():
    broker = Broker()
    broker.reply["result"]["validUntil"] = "999"
    with pytest.raises(KeyInfoEvidenceDenied, match="key_expired"):
        build(broker)()


def test_api_error_does_not_leak_sensitive_fields():
    broker = Broker()
    broker.reply = {"error": ["SECRETSHOULDNOTLEAK"]}
    with pytest.raises(KeyInfoEvidenceDenied, match="authenticated_key_read_unverified") as exc:
        build(broker)()
    assert "SECRET" not in str(exc.value)


def test_stale_slow_read_denied():
    broker = Broker()
    with pytest.raises(KeyInfoEvidenceDenied, match="clock_invalid_or_stale"):
        build(broker, now=[1000.0, 1062.0])()


def test_a_single_read_only_endpoint_only():
    broker = Broker()
    build(broker)()
    assert broker.calls == ["GetApiKeyInfo"]
