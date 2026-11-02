"""Synthetic exchange and ledger fixtures; no production account certification."""
import copy
import hashlib
import time
from types import SimpleNamespace

import pytest

from bot.kraken_position_sync_evidence import (
    KrakenPositionSyncDenied, make_kraken_position_sync_provider,
)

NOW = 1800000000.0


@pytest.fixture
def setup():
    key = "synthetic-position-test-key"
    iban = "synthetic-position-test-account"
    ledger = {"account": "platform:kraken", "provider_id": "test-ledger",
              "source": "independent_ledger", "snapshot_complete": True,
              "fills_reconciled": True, "positions_reconciled": True,
              "snapshot_id": "synthetic-revision", "observed_at_epoch": NOW - 2,
              "positions": {"lot1": {"pair": "BTCUSD", "side": "long", "quantity": "0.01"}}}
    broker = SimpleNamespace(connected=True, account_type="platform", broker_type="kraken", user_id=None)
    broker._startup_position_sync_fetch_ok = True
    broker._startup_position_sync_adopted = True
    broker._nija_authoritative_position_snapshot_fetch_ok_v285 = True
    broker._nija_authoritative_position_snapshot_generation_v285 = 5
    broker._nija_authoritative_position_snapshot_at_wall_v285 = NOW - 3
    broker._nija_authoritative_position_snapshot_at_monotonic_v285 = time.monotonic() - 3
    broker._nija_authoritative_position_snapshot_rows_v285 = [{"symbol": "BTC-USD", "quantity": 0.01}]
    responses = {
        "GetApiKeyInfo": {"apiKey": key, "iban": iban, "validUntil": "0"},
        "Balance": {"XXBT": "0.01", "ZUSD": "20.00"}, "OpenPositions": {},
    }
    calls = []

    def read(endpoint, params, *, category):
        assert params == {}
        assert category == "synthetic-monitoring"
        calls.append(endpoint)
        return {"error": [], "result": copy.deepcopy(responses[endpoint])}

    broker._kraken_private_call = read
    args = dict(broker=broker, account_scope="platform:kraken",
                approved_api_key_sha256=hashlib.sha256(key.encode()).hexdigest(),
                approved_iban_sha256=hashlib.sha256(("kraken\0" + iban.upper()).encode()).hexdigest(),
                reviewed_provider_id="test-position-sync", reviewed_ledger_provider_id="test-ledger",
                independent_positions=lambda: copy.deepcopy(ledger),
                monitoring_category="synthetic-monitoring", independently_reviewed=True, clock=lambda: NOW)
    return args, ledger, responses, calls


def test_compares_authenticated_spot_ledger_and_runtime_preserving_oldest_stamp(setup):
    args, _, _, calls = setup
    result = make_kraken_position_sync_provider(**args)()
    assert result["verified"] is True
    assert result["observed_at_epoch"] == NOW - 3
    assert result["expires_at_epoch"] == NOW + 57
    assert result["authorizes_orders"] is False
    assert calls == ["GetApiKeyInfo", "Balance", "OpenPositions", "Balance", "OpenPositions", "GetApiKeyInfo"]


@pytest.mark.parametrize("target", ["exchange", "ledger", "runtime"])
def test_quantity_mismatch_denies(setup, target):
    args, ledger, replies, _ = setup
    if target == "exchange":
        replies["Balance"]["XXBT"] = "0.02"
    elif target == "ledger":
        ledger["positions"]["lot1"]["quantity"] = "0.02"
    else:
        args["broker"]._nija_authoritative_position_snapshot_rows_v285[0]["quantity"] = 0.02
    with pytest.raises(KrakenPositionSyncDenied, match="inventory_mismatch"):
        make_kraken_position_sync_provider(**args)()


@pytest.mark.parametrize("asset", ["SOL", "XBT.F", "XETH.S", "BTC"])
def test_unmapped_or_duplicate_assets_deny(setup, asset):
    args, _, replies, _ = setup
    replies["Balance"][asset] = "1"
    with pytest.raises(KrakenPositionSyncDenied, match="unsupported_or_ambiguous"):
        make_kraken_position_sync_provider(**args)()


def test_empty_margin_is_not_proof_of_empty_spot(setup):
    args, ledger, _, _ = setup
    ledger["positions"] = {}
    args["broker"]._nija_authoritative_position_snapshot_rows_v285 = []
    with pytest.raises(KrakenPositionSyncDenied, match="inventory_mismatch"):
        make_kraken_position_sync_provider(**args)()


def test_margin_position_denies_supported_spot_scope(setup):
    args, _, replies, _ = setup
    replies["OpenPositions"] = {"synthetic-margin-position": {"vol": "1"}}
    with pytest.raises(KrakenPositionSyncDenied, match="margin_inventory"):
        make_kraken_position_sync_provider(**args)()


@pytest.mark.parametrize("field", ["fills_reconciled", "positions_reconciled", "snapshot_complete"])
def test_incomplete_ledger_denies(setup, field):
    args, ledger, _, _ = setup
    ledger[field] = False
    with pytest.raises(KrakenPositionSyncDenied, match="reconciled_ledger"):
        make_kraken_position_sync_provider(**args)()


@pytest.mark.parametrize("source", ["ledger", "runtime", "adoption", "malformed_row"])
def test_stale_unadopted_or_malformed_runtime_denies(setup, source):
    args, ledger, _, _ = setup
    broker = args["broker"]
    if source == "ledger":
        ledger["observed_at_epoch"] = NOW - 61
    elif source == "runtime":
        broker._nija_authoritative_position_snapshot_at_wall_v285 = NOW - 61
    elif source == "adoption":
        broker._startup_position_sync_adopted = False
    else:
        broker._nija_authoritative_position_snapshot_rows_v285.append(None)
    with pytest.raises(KrakenPositionSyncDenied):
        make_kraken_position_sync_provider(**args)()


def test_changing_exchange_read_denies(setup):
    args, _, replies, calls = setup
    original = args["broker"]._kraken_private_call

    def read(endpoint, params, *, category):
        if endpoint == "Balance" and "Balance" in calls:
            replies["Balance"]["XXBT"] = "0.02"
        return original(endpoint, params, category=category)

    args["broker"]._kraken_private_call = read
    with pytest.raises(KrakenPositionSyncDenied, match="sources_changed"):
        make_kraken_position_sync_provider(**args)()


def test_missing_identity_and_unreviewed_binding_fail_closed(setup):
    args, _, replies, _ = setup
    del replies["GetApiKeyInfo"]["apiKey"]
    with pytest.raises(KrakenPositionSyncDenied, match="read_unverified"):
        make_kraken_position_sync_provider(**args)()
    args["independently_reviewed"] = False
    with pytest.raises(KrakenPositionSyncDenied, match="independent_review"):
        make_kraken_position_sync_provider(**args)


def test_stricter_ledger_expiry_is_preserved(setup):
    args, ledger, _, _ = setup
    ledger["expires_at_epoch"] = NOW + 1
    assert make_kraken_position_sync_provider(**args)()["expires_at_epoch"] == NOW + 1
    ledger["expires_at_epoch"] = NOW
    with pytest.raises(KrakenPositionSyncDenied, match="ledger_source_expired"):
        make_kraken_position_sync_provider(**args)()


def test_runtime_configured_lifetime_is_not_widened(setup, monkeypatch):
    args, _, _, _ = setup
    monkeypatch.setenv("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "15")
    assert make_kraken_position_sync_provider(**args)()["expires_at_epoch"] == NOW + 12
    args["broker"]._nija_authoritative_position_snapshot_at_wall_v285 = NOW - 16
    with pytest.raises(KrakenPositionSyncDenied, match="runtime_snapshot_stale"):
        make_kraken_position_sync_provider(**args)()


def test_runtime_lifetime_change_during_collection_denies(setup, monkeypatch):
    args, _, _, _ = setup
    original = args["broker"]._kraken_private_call
    def read(endpoint, params, *, category):
        result = original(endpoint, params, category=category)
        if endpoint == "Balance":
            monkeypatch.setenv("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "15")
        return result
    args["broker"]._kraken_private_call = read
    with pytest.raises(KrakenPositionSyncDenied, match="position_sources_changed"):
        make_kraken_position_sync_provider(**args)()
