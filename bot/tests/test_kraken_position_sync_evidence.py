"""Synthetic exchange and ledger fixtures; no production account certification."""
import copy
import hashlib
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

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


@pytest.fixture
def native_position_sources() -> Iterator[SimpleNamespace]:
    """Join the real SQLite ledger reader to position sync with an offline broker."""
    from bot.kraken_ledger_evidence import ReviewedLedgerBinding, make_kraken_ledger_evidence_provider
    from bot.tests import test_kraken_ledger_evidence as ledger_fixture

    fixture = ledger_fixture.KrakenLedgerEvidenceTests()
    fixture.setUp()
    try:
        broker = fixture.broker
        broker.account_type = "platform"
        broker.user_id = None
        for table in ledger_fixture._COLUMNS:
            fixture.update(table, "account_scope", "platform:kraken")
        for table in ("trade_ledger", "open_positions", "pending_kraken_closes"):
            fixture.update(table, "user_id", "platform")

        def margin_response(endpoint: str, params: dict) -> dict | None:
            """Supply only the additional read-only margin endpoint used by sync."""
            return {"error": [], "result": {}} if endpoint == "OpenPositions" else None

        broker.hook = margin_response
        broker._startup_position_sync_fetch_ok = True
        broker._startup_position_sync_adopted = True
        broker._nija_authoritative_position_snapshot_fetch_ok_v285 = True
        broker._nija_authoritative_position_snapshot_generation_v285 = 5
        broker._nija_authoritative_position_snapshot_at_wall_v285 = NOW - 3
        broker._nija_authoritative_position_snapshot_at_monotonic_v285 = time.monotonic() - 3
        broker._nija_authoritative_position_snapshot_rows_v285 = [{"symbol": "BTC-USD", "quantity": "2"}]
        binding = ReviewedLedgerBinding(
            broker=broker, account="platform:kraken", provider_id="native-offline-ledger",
            api_key_sha256=ledger_fixture.KEY_HASH, account_sha256=ledger_fixture.ACCOUNT_HASH,
            ledger_path=fixture.path, persistent_root=fixture.root,
            monitoring_category=fixture.binding.monitoring_category,
        )
        native_reader = make_kraken_ledger_evidence_provider(
            binding, review_binding=lambda candidate: candidate is binding, clock=lambda: NOW,
        )
        observations = []

        def read_ledger() -> Any:
            """Record original receipts so mutation or ID reuse is observable."""
            observation = native_reader()
            observations.append(observation)
            return observation

        args = dict(
            broker=broker, account_scope=binding.account,
            approved_api_key_sha256=binding.api_key_sha256,
            approved_iban_sha256=binding.account_sha256,
            reviewed_provider_id="native-offline-position-sync",
            reviewed_ledger_provider_id=binding.provider_id,
            independent_positions=read_ledger, monitoring_category=binding.monitoring_category,
            independently_reviewed=True, clock=lambda: NOW,
        )
        yield SimpleNamespace(fixture=fixture, args=args, observations=observations, binding=binding)
    finally:
        fixture.tearDown()


def test_real_ledger_receipt_ids_do_not_masquerade_as_changed_position_state(
    native_position_sources: SimpleNamespace,
) -> None:
    """A complete unchanged persisted ledger must integrate despite fresh receipts."""
    sources = native_position_sources
    before = sources.fixture.path.read_bytes()
    result = make_kraken_position_sync_provider(**sources.args)()
    first, second = sources.observations

    assert first["evidence_id"] != second["evidence_id"]
    assert all(isinstance(row["evidence_id"], str) and len(row["evidence_id"]) == 32 for row in (first, second))
    assert {key for key in first if first[key] != second[key]} == {"evidence_id"}
    assert result["evidence_id"] not in {first["evidence_id"], second["evidence_id"]}
    assert result["verified"] is True
    assert result["read_only"] is True
    assert result["authorizes_orders"] is False
    assert result["observed_at_epoch"] == NOW - 10
    assert result["expires_at_epoch"] == NOW + 50
    assert sources.fixture.path.read_bytes() == before
    assert {endpoint for endpoint, _, _ in sources.fixture.broker.calls} == {
        "GetApiKeyInfo", "Balance", "OpenPositions", "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders",
    }
    assert all(category is sources.binding.monitoring_category for _, _, category in sources.fixture.broker.calls)


@pytest.mark.parametrize("table,field,value,reason", [
    ("ledger_evidence_state", "revision", "persisted-revision-2", "position_sources_changed"),
    ("ledger_evidence_state", "observed_at_epoch", NOW - 9, "position_sources_changed"),
    ("ledger_evidence_state", "observed_at_epoch", NOW - 61, "position_sync_read_unverified"),
    ("ledger_evidence_state", "history_from_genesis", 0, "position_sync_read_unverified"),
    ("trade_ledger", "api_key_sha256", "a" * 64, "position_sync_read_unverified"),
    ("trade_ledger", "account_sha256", "b" * 64, "position_sync_read_unverified"),
    ("ledger_evidence_state", "account_scope", "user:elsewhere:kraken", "position_sync_read_unverified"),
    ("open_positions", "quantity", "3", "position_sync_read_unverified"),
    ("ledger_open_orders", "price", "101", "position_sync_read_unverified"),
])
def test_real_ledger_source_changes_still_deny(
    native_position_sources: SimpleNamespace, table: str, field: str, value: Any, reason: str,
) -> None:
    """Fresh receipt IDs never conceal persisted state, attribution or time changes."""
    sources = native_position_sources
    original = sources.args["independent_positions"]
    reads = 0

    def changed_reader() -> Any:
        nonlocal reads
        reads += 1
        if reads == 2:
            sources.fixture.update(table, field, value)
        return original()

    sources.args["independent_positions"] = changed_reader
    with pytest.raises(KrakenPositionSyncDenied, match=reason):
        make_kraken_position_sync_provider(**sources.args)()
    assert reads == 2


@pytest.mark.parametrize("field,value", [
    ("account", "user:elsewhere:kraken"), ("provider_id", "other-ledger"), ("source", "broker_cache"),
    ("snapshot_id", "different-persisted-revision"), ("observed_at_epoch", NOW - 1),
    ("expires_at_epoch", NOW + 10), ("verified", False), ("read_only", False),
    ("scope_verified", False), ("authorizes_orders", True), ("pending_closes_reconciled", False),
    ("outstanding_intents_reconciled", False), ("unresolved_submission_count", 1),
    ("positions", {"lot1": {"pair": "BTCUSD", "side": "long", "quantity": "0.02"}}),
    ("orders", {"synthetic-intent": {"quantity": "0.02"}}),
    ("provenance", {"ledger_snapshot_verified": False}),
    ("api_key_sha256", "b" * 64), ("account_sha256", "d" * 64),
    ("source_metadata", {"evidence_id": "different-source-annotation"}),
    ("new_source_metadata", "unexpected-source-change"),
])
def test_only_top_level_receipt_value_is_exempt_from_stability_comparison(
    setup: tuple, field: str, value: Any,
) -> None:
    """All other supplied fields, including unknown and nested metadata, still bind."""
    args, ledger, _, _ = setup
    ledger.update(
        evidence_id="synthetic-receipt-1", verified=True, read_only=True, scope_verified=True,
        authorizes_orders=False, expires_at_epoch=NOW + 20,
        pending_closes_reconciled=True, outstanding_intents_reconciled=True,
        unresolved_submission_count=0, orders={"synthetic-intent": {"quantity": "0.01"}},
        provenance={"ledger_snapshot_verified": True}, api_key_sha256="a" * 64,
        account_sha256="c" * 64, source_metadata={"evidence_id": "source-annotation"},
    )
    reads = 0

    def changed_reader() -> dict:
        nonlocal reads
        reads += 1
        snapshot = copy.deepcopy(ledger)
        snapshot["evidence_id"] = "synthetic-receipt-" + str(reads)
        if reads == 2:
            snapshot[field] = value
        return snapshot

    args["independent_positions"] = changed_reader
    with pytest.raises(KrakenPositionSyncDenied):
        make_kraken_position_sync_provider(**args)()
    assert reads == 2


@pytest.mark.parametrize("receipt", [None, 1, True, {}, [], "", " leading", "trailing ", "embedded\nspace"])
def test_malformed_ledger_receipt_id_is_not_discarded_as_metadata(setup: tuple, receipt: Any) -> None:
    """Only a valid optional identifier can receive per-observation treatment."""
    args, ledger, _, _ = setup
    ledger["evidence_id"] = receipt
    with pytest.raises(KrakenPositionSyncDenied, match="ledger_evidence_identity_invalid"):
        make_kraken_position_sync_provider(**args)()


def test_ledger_receipt_id_presence_cannot_change_between_reads(setup: tuple) -> None:
    """Legacy sources may omit receipt IDs consistently, never switch contract mid-read."""
    args, ledger, _, _ = setup
    reads = 0

    def changed_reader() -> dict:
        nonlocal reads
        reads += 1
        snapshot = copy.deepcopy(ledger)
        if reads == 1:
            snapshot["evidence_id"] = "synthetic-receipt"
        return snapshot

    args["independent_positions"] = changed_reader
    with pytest.raises(KrakenPositionSyncDenied, match="position_sources_changed"):
        make_kraken_position_sync_provider(**args)()
