"""Synthetic-only regressions for the read-only Kraken account identity provider."""
import hashlib

import pytest

from bot.kraken_authenticated_identity_v480 import (
    KrakenIdentityDenied, make_kraken_account_identity_provider,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate

API_KEY = "synthetic-public-key-identifier"
IIBAN = "AA00 TEST TEST TEST"
SCOPE = "platform:kraken"
CATEGORY = object()
PID = "independently-reviewed-kraken-identity-1"
KEY_PIN = hashlib.sha256(API_KEY.encode("utf-8")).hexdigest()
ACCOUNT_PIN = hashlib.sha256(("kraken\0" + IIBAN).encode("utf-8")).hexdigest()


class Broker:
    connected = True
    broker_type = "kraken"
    account_type = "platform"
    user_id = None

    def __init__(self):
        self.calls = []
        self.on_call = None
        self.reply = {"error": [], "result": {
            "apiKey": API_KEY, "iban": IIBAN, "validUntil": "0",
        }}

    def _kraken_private_call(self, endpoint, params, *, category):
        assert (endpoint, params, category) == ("GetApiKeyInfo", {}, CATEGORY)
        self.calls.append(endpoint)
        if self.on_call is not None:
            self.on_call()
        return self.reply


def make(broker, *, account_pin=ACCOUNT_PIN, key_pin=KEY_PIN, scope=SCOPE, times=None):
    ticks = iter(times if times is not None else [1000.0, 1001.0])
    return make_kraken_account_identity_provider(
        broker, account_scope=scope, approved_iban_sha256=account_pin,
        approved_api_key_sha256=key_pin, reviewed_provider_id=PID,
        monitoring_category=CATEGORY, clock=lambda: next(ticks),
    )


def test_account_and_key_both_pinned_but_not_execution_authority():
    broker = Broker()
    observation = make(broker)()
    assert broker.calls == ["GetApiKeyInfo"]
    assert observation["account"] == SCOPE
    assert observation["source"] == "authenticated_broker"
    assert observation["verified"] is True
    assert observation["read_only"] is True
    assert API_KEY not in repr(observation)
    assert IIBAN not in repr(observation)
    assert KEY_PIN not in repr(observation)
    assert ACCOUNT_PIN not in repr(observation)
    ids = {field: "reviewed-" + field for field in REQUIRED}
    ids["account_identity"] = PID
    certificate = evaluate_pretrade_certificate(
        {"account_identity": observation}, account=SCOPE,
        trusted_provider_ids=ids, now_epoch=1001.0,
    )
    assert certificate["certified"] is False
    assert "protective_exit_readback" in certificate["missing"]
    assert certificate["authorizes_orders"] is False


@pytest.mark.parametrize("bad_pin", ["", "unverified", "0"*63, "z"*64])
def test_unreviewed_pin_rejected_without_broker_io(bad_pin):
    broker = Broker()
    with pytest.raises(KrakenIdentityDenied, match="pins_required"):
        make(broker, account_pin=bad_pin)
    assert not broker.calls


def test_wrong_account_or_key_denied():
    broker = Broker()
    with pytest.raises(KrakenIdentityDenied, match="broker_account_mismatch"):
        make(broker, account_pin="a"*64)()
    with pytest.raises(KrakenIdentityDenied, match="api_key_identity_mismatch"):
        make(broker, key_pin="b"*64)()
    assert len(broker.calls) == 2


def test_disconnected_or_wrong_scope_rejected_before_network():
    broker = Broker()
    broker.connected = False
    with pytest.raises(KrakenIdentityDenied, match="client_unavailable"):
        make(broker)()
    broker.connected = True
    broker.account_type = "user"
    broker.user_id = "other"
    with pytest.raises(KrakenIdentityDenied, match="scope_mismatch"):
        make(broker)()
    assert not broker.calls


def test_account_switch_during_private_read_denied():
    broker = Broker()
    broker.on_call = lambda: setattr(broker, "connected", False)
    with pytest.raises(KrakenIdentityDenied, match="scope_changed"):
        make(broker)()


@pytest.mark.parametrize("expiry", [None, "", "-1", "999", True])
def test_invalid_or_expired_key_cannot_certify(expiry):
    broker = Broker()
    broker.reply["result"]["validUntil"] = expiry
    with pytest.raises(KrakenIdentityDenied, match="expiry_unverified|key_expired"):
        make(broker)()


def test_invalid_identity_or_api_error_safely_denied():
    broker = Broker()
    broker.reply["result"]["iban"] = ""
    with pytest.raises(KrakenIdentityDenied, match="account_identifier_invalid"):
        make(broker)()
    broker.reply = {"error": ["PRIVATE-SECRET"], "result": {"iban": IIBAN, "apiKey": API_KEY}}
    with pytest.raises(KrakenIdentityDenied, match="identity_read_unverified") as e:
        make(broker)()
    assert "PRIVATE-SECRET" not in str(e.value)


def test_stale_or_future_clock_denied():
    broker = Broker()
    with pytest.raises(KrakenIdentityDenied, match="clock_invalid_or_stale"):
        make(broker, times=[1000.0, 1062.0])()
    with pytest.raises(KrakenIdentityDenied, match="clock_invalid_or_stale"):
        make(broker, times=[1001.0, 1000.0])()


def test_no_automatic_registration_or_trading_side_effects():
    from bot import pretrade_independent_attestation as att
    broker = Broker()
    before = att._COLLECTOR
    build = make(broker)
    assert att._COLLECTOR is before
    assert broker.calls == []
    build()
    assert att._COLLECTOR is before
