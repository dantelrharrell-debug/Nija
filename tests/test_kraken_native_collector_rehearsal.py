"""Offline protected startup through all native readers with one synthetic spot lot."""
import copy
import multiprocessing
import socket
import sqlite3
import sys
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot import kraken_ledger_evidence as native_ledger
from bot import kraken_native_four_source_binding as four
from bot import kraken_redis_evidence as redis
from bot import kraken_startup_evidence_binding as startup
from bot import kraken_protected_startup_root as root
from bot import pretrade_independent_attestation as diagnostic
from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.startup_two_phase_policy_v8 import evaluate_startup_transition
from bot.tests import test_kraken_ledger_evidence as ledger_data
from bot.tests import test_kraken_operator_authorization as operator_data
from bot.tests import test_kraken_redis_evidence as redis_data
from bot.tests import test_kraken_risk_evidence as risk_data
from bot.tests import test_kraken_position_sync_evidence as position_data
from bot.tests import test_kraken_kill_switch_evidence as kill_data
import test_kraken_protected_startup_root as startup_data

# Register existing synthetic pytest fixtures under their dependency names.
native_position_sources = position_data.native_position_sources
kill_source = kill_data.setup
protected = startup_data.protected
wiring = startup_data.wiring
fixture = startup_data.fixture

pytestmark = pytest.mark.parametrize("fixture", [(ledger_data.ACCOUNT_HASH, ledger_data.KEY_HASH)], indirect=True)
READ_ENDPOINTS = {"GetApiKeyInfo", "Balance", "BalanceEx", "OpenPositions", "OpenOrders",
                  "ClosedOrders", "TradesHistory", "Ledgers"}


def signed_operator(trust, now):
    records = operator_data.OperatorAuthorizationTests()
    records.setUp()
    binding = four.GeneralApprovalBinding(
        "platform:kraken", trust.account_iiban_sha256, trust.api_key_sha256, "spot",
        ("general_live_orders",), trust.release_id, trust.reviewed_provider_ids["operator_authorization"],
    )
    records.approval.update(account_iiban_sha256=binding.account_iiban_sha256,
                            api_key_sha256=binding.api_key_sha256, release_id=binding.release_id,
                            approved_at_epoch=now - 3, expires_at_epoch=now + 50)
    records.status.update(observed_at_epoch=now - 1, expires_at_epoch=now + 40)
    records.resign()
    return four.ReviewedOperatorSource(binding, {"test-operator": records.public(records.operator)},
                                       records.public(records.revoker), lambda: records.records)


def wire_writer(broker, inventory, monkeypatch):
    scope = inventory.scope
    controls = [key for _, key in inventory.reader()._controls()]
    values = inventory.redis.values
    key_id = scope.api_key_sha256[:16]

    def process_fence():
        assert values[controls[0]].decode() == scope.process_lock_value

    def lease(key):
        assert key == key_id
        return dict(enabled=True, key_id=key, owner_id=values[controls[2]].decode(),
                    owner_fingerprint=values[controls[5]].decode(), token=int(values[controls[3]]),
                    ttl_remaining_ms=inventory.redis.ttls[controls[3]], stable_for_s=20)

    def last_nonce(key):
        assert key == key_id
        return int(values[controls[6]])

    monkeypatch.setitem(sys.modules, "bot.execution_authority_context",
                        SimpleNamespace(assert_distributed_writer_authority=process_fence))
    broker._distributed_nonce_manager = SimpleNamespace(
        _redis=inventory.redis, _strict_redis_lease=True, _owner_id=scope.nonce_owner,
        _owner_fingerprint=scope.nonce_fingerprint, lease_version=scope.nonce_lease_version,
        get_writer_lease_status=lease, get_last_nonce=last_nonce,
    )
    broker._nonce_key_id = key_id
    broker._nonce_lease_version = scope.nonce_lease_version
    broker._kraken_private_call_nonce = Mock(side_effect=AssertionError("nonce write"))
    broker.api = SimpleNamespace(key=broker.key, _nonce=broker._kraken_private_call_nonce)


def bind_opening(ledger, journal, now, fault):
    broker = ledger.broker
    cutoff = now - 10
    broker.data["ClosedOrders"][ledger_data.BUY]["closetm"] = cutoff - 1
    for row in broker.data["Ledgers"].values():
        row["time"] = cutoff - 1

    # The opening holding has no locally attributed historical fill.
    # Retain a legacy terminal close outside the current opening lot.
    legacy_order = ledger_data.SELL
    broker.data["ClosedOrders"][legacy_order] = {
        **ledger_data.order(executed="2"), "status": "closed", "closetm": cutoff - 1, "fee": "2",
    }
    with sqlite3.connect(journal.path) as db:
        db.execute("DELETE FROM trade_ledger")
    journal.scope["account_scope"] = ledger.account
    journal.insert("pending_kraken_closes", {
        "user_id": "platform", "exchange_order_id": legacy_order,
        "state": "historical_unattributed", "symbol": "BTC-USD", "side": "sell",
        "position_id": "legacy-lot", "quantity": "2", "executed": "2", "fee": "2",
    })
    db, _, _ = native_ledger._open(ledger)
    try:
        local = native_ledger._snapshot(db, ledger, now)
    finally:
        db.close()
    history = {key: broker.data[endpoint] for key, endpoint in (
        ("trades", "TradesHistory"), ("closed", "ClosedOrders"), ("ledger", "Ledgers"),
    )}
    baseline = native_ledger.ReviewedOpeningBaseline(
        account=ledger.account, account_sha256=ledger.account_sha256, api_key_sha256=ledger.api_key_sha256,
        cutoff_epoch=cutoff, expires_at_epoch=now + 45, history_sha256=native_ledger._digest(history),
        historical_rows_sha256=native_ledger._digest({
            key: local[key] for key in ("trade_ledger", "pending_kraken_closes")
        }),
        opening_inventory_sha256=native_ledger._digest({
            "balance": broker.balance, "positions": local["open_positions"], "orders": local["ledger_open_orders"],
        }),
    )
    journal.update("ledger_evidence_state", "history_from_genesis", 0)
    if fault == "missing":
        return ledger
    if fault == "stale":
        baseline = replace(baseline, expires_at_epoch=now - 1)
    if fault == "wrong-account":
        baseline = replace(baseline, account_sha256="0" * 64)
    if fault == "holding":
        broker.balance["XXBT"] = "3"
    if fault == "order":
        broker.data["OpenOrders"][ledger_data.SELL] = ledger_data.order()
    if fault == "intent":
        journal.update("ledger_evidence_state", "unresolved_submission_count", 1)
    if fault == "exit":
        del broker.data["OpenOrders"][ledger_data.STOP]
    if fault == "replay":
        broker.data["TradesHistory"][ledger_data.TID]["time"] = cutoff + 1
    if fault == "legacy-change":
        journal.update("pending_kraken_closes", "fee", "3")
    return replace(ledger, opening_baseline=baseline)


@pytest.fixture
def rehearsal(protected, native_position_sources, kill_source, monkeypatch, request):
    now = time.time()
    w = protected.wiring
    trust = w.signed.trust
    ids = trust.reviewed_provider_ids
    ledger = replace(native_position_sources.binding, provider_id=ids["position_ledger_reconciliation"])
    journal = native_position_sources.fixture
    journal.update("ledger_evidence_state", "observed_at_epoch", now - 3)
    fault = getattr(request, "param", None)
    if fault is not None:
        ledger = bind_opening(ledger, journal, now, fault)
    broker = ledger.broker
    broker._nija_authoritative_position_snapshot_at_wall_v285 = now - 2
    w.sources.manager.platform_brokers = {"kraken": broker}
    monkeypatch.setitem(sys.modules, "bot.broker_manager", SimpleNamespace(KrakenBroker=type(broker)))
    broker.place_order = Mock(side_effect=AssertionError("order submission"))
    broker.cancel_order = Mock(side_effect=AssertionError("order cancellation"))
    network = Mock(side_effect=AssertionError("network access"))
    monkeypatch.setattr(socket.socket, "connect", network)
    monkeypatch.setattr(socket.socket, "connect_ex", network)

    def extra_read(endpoint, params):
        assert endpoint in READ_ENDPOINTS
        if endpoint == "GetApiKeyInfo":
            result = dict(apiKey=broker.key, iban=broker.iban, validUntil="0", queryFrom="0", queryTo="0",
                          permissions=["query-funds", "query-open-trades", "query-closed-trades", "query-ledger"])
        elif endpoint == "BalanceEx":
            result = {k: {"balance": v, "hold_trade": "0", "credit": "0", "credit_used": "0"}
                      for k, v in broker.balance.items()}
        elif endpoint == "OpenPositions":
            result = {"position": {"margin": "1"}} if fault == "margin" else {}
        else:
            return None
        return {"result": result, "error": []}

    broker.hook = extra_read
    inventory = redis_data.RedisEvidenceTests()
    inventory.configure_inventory(trust.api_key_sha256, tuple(ids[k] for k in redis.FIELDS), trust.image_sha256)
    wire_writer(broker, inventory, monkeypatch)
    scope = redis.ScopeObservation(**vars(inventory.scope))
    inventory_binding = redis.ReviewedBinding(**(vars(inventory.binding) | {
        "expected_scope": scope, "observe_scope": lambda: scope,
    }))
    snapshot = risk_data.snapshot(pin=trust.api_key_sha256)
    for row in (snapshot, snapshot["policy"], snapshot["exposure"], snapshot["capital"]):
        row["observed_at_epoch"] = now - 1
    position = snapshot["exposure"]["positions"][0]
    position.update(quantity=2, protected_quantity=2, notional_usd=200, risk_usd=4, position_id="internal-lot-1")
    snapshot["exposure"].update(total_gross_exposure_usd=200, total_risk_usd=4)
    snapshot["policy"].update(max_position_pct=25, max_single_asset_pct=25)
    bundle = four.ReviewedNativeFourSources(
        manager=w.sources.manager, strategy=w.sources.strategy, broker=broker, service_id=trust.service_id,
        release_id=trust.release_id, image_sha256=trust.image_sha256, ledger_binding=ledger,
        review_ledger_binding=lambda b: b is ledger, redis=four.ReviewedRedisSource(inventory.redis, inventory_binding),
        operator=signed_operator(trust, now),
        risk=four.ReviewedRiskSource(risk_data.SnapshotSource(snapshot), snapshot["source_id"], risk_data.BINDINGS),
    )
    client = kill_source[1]
    client.pipeline = lambda: type(client.pipe)(client)
    kill = replace(kill_source[0], api_key_sha256=trust.api_key_sha256, provider_id=ids["kill_switch_clear"])
    w.sources = replace(w.sources, broker=broker, native_four_sources=bundle, review_native_four_sources=lambda b: b is bundle,
                        kill_switch_binding=kill, review_kill_switch_binding=lambda b: b is kill, independent_remaining={},
                        use_native_ledger_readers=True, independent_positions=None, independent_open_intents=None,
                        monitoring_category=ledger.monitoring_category)
    protected.bridge.review.side_effect = lambda s, trust: (
        trust == w.signed.trust and s.native_four_sources is bundle and s.kill_switch_binding is kill
        and s.broker is broker and s.manager.platform_brokers["kraken"] is broker)
    yield SimpleNamespace(protected=protected, sources=w.sources, broker=broker, journal=journal, inventory=inventory,
                          network=network)
    network.assert_not_called()
    broker._kraken_private_call_nonce.assert_not_called()
    assert all(endpoint in READ_ENDPOINTS for endpoint, _, _ in broker.calls)


def boot(r):
    assert root.register_from_protected_root() == "protected_startup_factory_registered"
    return startup.install_from_canonical_startup(r.sources.manager, r.sources.strategy)


def assert_complete(r):
    files = [r.journal.path, r.protected.directory / root.SOURCE_NAME, r.protected.directory / root.MANIFEST_NAME]
    before = [path.read_bytes() for path in files]
    inventory = copy.deepcopy(r.inventory.redis.values)
    assert boot(r) == "diagnostic_collector_installed"
    report = diagnostic.inspect_authenticated_attestations("platform:kraken")
    assert set(report["checks"]) == set(REQUIRED)
    assert all(report["checks"].values()), [k for k, v in report["checks"].items() if not v]
    assert report["authorizes_orders"] is False
    checks = report["checks"]
    facts = {
        "authenticated_pretrade_certificate": all(checks.values()),
        "broker_permissions": checks["account_permissions"],
        "broker_identity": checks["account_identity"],
        "broker_balances": checks["broker_balances"],
        "ledger_reconciled": checks["position_ledger_reconciliation"],
        "protective_exits_verified": checks["protective_exit_readback"],
        "open_orders_reconciled": checks["open_order_reconciliation"],
        "duplicate_fence_clear": checks["duplicate_order_fence"],
        "writer_lease_valid": checks["writer_lease"],
        "nonce_ready": checks["nonce_sequence"],
        "risk_ready": checks["risk_limits"],
        "strategy_ready": checks["position_sync"],
        "capital_ready": True,
        "kill_switch_clear": checks["kill_switch_clear"],
        "operator_authorized": checks["operator_authorization"],
        "account_scope_verified": checks["account_identity"],
        "backup_restore_certified": True,
    }
    decision = evaluate_startup_transition(facts, pending_execution=False, posttrade_verified=False)
    assert decision["pretrade_candidate_ready"] is True
    assert decision["activation_allowed"] is False
    pending = evaluate_startup_transition(facts, pending_execution=True, posttrade_verified=False)
    assert pending["pretrade_candidate_ready"] is False
    r.broker.place_order.assert_not_called()
    r.broker.cancel_order.assert_not_called()
    assert before == [path.read_bytes() for path in files]
    assert inventory == r.inventory.redis.values
    assert {method for method, _, _ in r.broker.calls} == READ_ENDPOINTS
    r.network.assert_not_called()
    r.broker._kraken_private_call_nonce.assert_not_called()


@pytest.mark.parametrize("rehearsal", [None, "opening"], indirect=True)
def test_native_install_and_restart(rehearsal):
    # Each child inherits the unregistered parent and reopens the same protected files and database.
    assert diagnostic._COLLECTOR is None
    for _ in range(2):
        child = multiprocessing.get_context("fork").Process(target=assert_complete, args=(rehearsal,))
        child.start()
        child.join(15)
        if child.is_alive():
            child.kill()
            child.join()
        assert child.exitcode == 0


@pytest.mark.parametrize("fault", ["absent_inventory", "stale_ledger", "wrong_account", "invalid_receipt"])
def test_reject_incomplete_install(rehearsal, fault):
    r = rehearsal
    if fault == "absent_inventory":
        del r.inventory.redis.values[r.inventory.manifest_key]
    elif fault == "stale_ledger":
        r.journal.update("ledger_evidence_state", "observed_at_epoch", time.time() - 3600)
    elif fault == "wrong_account":
        r.broker.iban = "different-synthetic-account"
    else:
        r.protected.write(change=lambda m: m["receipts"].update(independent_review="invalid"))
        assert root.register_from_protected_root() == "protected_startup_receipts_denied"
        assert diagnostic._COLLECTOR is None
        return
    assert boot(r) == "collector_registration_failed"
    assert diagnostic._COLLECTOR is None
    report = diagnostic.inspect_authenticated_attestations("platform:kraken")
    assert not all(report["checks"].values())
    assert report["authorizes_orders"] is False


@pytest.mark.parametrize("rehearsal", [
    "missing", "stale", "wrong-account", "holding", "margin", "order", "intent", "exit", "replay", "legacy-change",
], indirect=True)
def test_opening_denials_through_protected_startup(rehearsal):
    assert boot(rehearsal) == "collector_registration_failed"
    report = diagnostic.inspect_authenticated_attestations("platform:kraken")
    assert not all(report["checks"].values())
    assert report["authorizes_orders"] is False
