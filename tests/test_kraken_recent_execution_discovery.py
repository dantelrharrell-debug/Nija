"""Offline authenticated-read regressions; no live brokers or order mutations."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot import runtime_known_execution_probe_revalidation_v406_patch as v406
from bot import runtime_kraken_delayed_fill_reconciliation_v357_patch as v357
from bot import runtime_kraken_deferred_fill_proof_recovery_v363_patch as v363


def _row(**changes):
    result = {
        "status": "closed", "opentm": 1.0, "closetm": 9990.0,
        "vol_exec": "0.1", "cost": "10.00",
        "descr": {"pair": "ETHUSD", "type": "buy"},
    }
    result.update(changes)
    return result


@pytest.fixture
def runtime(monkeypatch):
    broker = SimpleNamespace(broker_type="kraken")
    calls = []
    response = {"error": [], "result": {"closed": {"RECENT": _row()}}}

    def private_read(selected_broker, method, params):
        assert selected_broker is broker
        assert method in {"ClosedOrders", "QueryOrders"}
        calls.append((method, dict(params)))
        return response

    monkeypatch.setattr(v406.time, "time", lambda: 10000.0)
    monkeypatch.setattr(v406.time, "monotonic", lambda: 500.0)
    monkeypatch.setattr(v406, "_RECENT_DISCOVERY_RECHECK_AT", 0.0)
    monkeypatch.setattr(v406, "_HISTORICAL_ORDER_RECHECK_AT", {})
    monkeypatch.setattr(v406, "_candidate_brokers", lambda: [broker])
    monkeypatch.setattr(v357, "_recovery_scope", lambda selected: {
        "broker": "kraken", "account": "platform:kraken", "account_id": "platform:kraken",
    } if selected is broker else {})
    monkeypatch.setattr(v357, "_private_read", private_read)
    return broker, response, calls


def test_old_opening_recent_close_is_discovered_with_fixed_freshness(runtime):
    _, _, calls = runtime
    assert v406._recent_candidate_order_ids() == ["RECENT"]
    assert calls == [("ClosedOrders", {
        "start": 8199, "end": 10000, "closetime": "close",
        "trades": False, "without_count": True,
    })]


@pytest.mark.parametrize("change", [
    {"status": "canceled"}, {"status": "pending"}, {"status": "open"},
    {"closetm": 8199.99}, {"closetm": 10000.01}, {"closetm": 0},
    {"closetm": "nan"}, {"closetm": "inf"},
    {"vol_exec": "0"}, {"vol_exec": "nan"}, {"vol_exec": True},
    {"cost": "0"}, {"cost": "inf"}, {"cost": True},
    {"descr": {}}, {"descr": {"pair": "ETHUSD", "type": "unknown"}},
])
def test_unproven_or_stale_discovery_rows_never_become_candidates(runtime, change):
    _, response, _ = runtime
    response["result"]["closed"]["RECENT"] = _row(**change)
    assert v406._recent_candidate_order_ids() == []


def test_exact_1800_second_boundary_is_preserved(runtime):
    _, response, _ = runtime
    response["result"]["closed"]["RECENT"] = _row(closetm=8200.0)
    assert v406._recent_candidate_order_ids() == ["RECENT"]


@pytest.mark.parametrize("scope", [
    {}, {"broker": "kraken", "account": "user:a:kraken", "account_id": "user:a:kraken"},
    {"broker": "kraken", "account": "platform:kraken", "account_id": "user:a:kraken"},
])
def test_unregistered_user_or_shared_scope_never_queries_platform_history(runtime, monkeypatch, scope):
    _, _, calls = runtime
    monkeypatch.setattr(v357, "_recovery_scope", lambda broker: scope)
    assert v406._recent_candidate_order_ids() == []
    assert calls == []


def test_ambiguous_platform_instances_never_query(runtime, monkeypatch):
    _, _, calls = runtime
    monkeypatch.setattr(v406, "_candidate_brokers", lambda: [object(), object()])
    monkeypatch.setattr(v357, "_recovery_scope", lambda broker: {
        "broker": "kraken", "account": "platform:kraken", "account_id": "platform:kraken",
    })
    assert v406._recent_candidate_order_ids() == []
    assert calls == []


def test_discovery_throttles_authenticated_reads_without_caching_proof(runtime):
    _, _, calls = runtime
    assert v406._recent_candidate_order_ids() == ["RECENT"]
    assert v406._recent_candidate_order_ids() == []
    assert len(calls) == 1


def test_single_page_and_candidate_limits_are_bounded(runtime):
    _, response, calls = runtime
    response["result"]["closed"] = {
        f"ORDER-{i:02d}": _row(closetm=9900.0 + i) for i in range(50)
    }
    assert v406._recent_candidate_order_ids() == [f"ORDER-{i:02d}" for i in range(49, 39, -1)]
    assert len(calls) == 1


def test_private_error_is_not_execution_evidence_or_echoed(runtime, caplog):
    _, response, _ = runtime
    response["error"] = ["provider-sensitive-error"]
    assert v406._recent_candidate_order_ids() == []
    assert "provider-sensitive-error" not in caplog.text


def test_private_read_exception_fails_closed_and_is_redacted(runtime, monkeypatch, caplog):
    def unavailable(*args):
        raise RuntimeError("provider-sensitive-error")
    monkeypatch.setattr(v357, "_private_read", unavailable)
    assert v406._recent_candidate_order_ids() == []
    assert "provider-sensitive-error" not in caplog.text


def test_wrong_exact_queryorders_key_never_proves_discovered_order(runtime):
    _, response, calls = runtime
    response["result"] = {"UNRELATED": _row()}
    assert v406._final_authenticated_row("RECENT") == (None, None)
    assert calls == [("QueryOrders", {"txid": "RECENT", "trades": True})]


def test_fresh_discovery_is_only_a_candidate_not_canonical_readiness(runtime, monkeypatch):
    _, _, calls = runtime
    monkeypatch.setattr(v406, "_marker_ready", lambda: False)
    monkeypatch.setattr(v406, "_candidate_order_ids", lambda: [])
    assert v406.recover_once() is False
    assert [method for method, _ in calls] == ["ClosedOrders", "QueryOrders"]


@pytest.mark.parametrize("change", [
    {"broker_fill_at_epoch": 8199.0}, {"broker_fill_at_epoch": 10001.0},
    {"broker_fill_at_epoch": 0.0}, {"order_id": "UNRELATED"},
    {"kraken_query_order_reconciled": False}, {"kraken_query_order_reconciled": "true"},
])
def test_failed_second_lookup_cannot_inherit_first_lookup_freshness(runtime, monkeypatch, change):
    broker, _, _ = runtime
    enriched = {"order_id": "RECENT", "broker_fill_at_epoch": 9990.0,
                "kraken_query_order_reconciled": True}
    enriched.update(change)
    promoted = []
    monkeypatch.setattr(v357, "_enrich_kraken_final_order", lambda *args, **kwargs: enriched)
    monkeypatch.setattr(v363, "_promote_confirmed_fill", lambda *args, **kwargs: promoted.append(args))
    assert v406._promote_same_authenticated_row("RECENT", broker, _row()) == (False, 0)
    assert promoted == []


def test_canonical_recovery_is_required_after_exact_authenticated_read(runtime, monkeypatch):
    broker, response, calls = runtime
    response["result"] = {"RECENT": _row()}
    proof = []
    monkeypatch.setattr(v363, "_promote_confirmed_fill", lambda *args, **kwargs: proof.append(args[0]) or True)
    monkeypatch.setattr(v363, "_discard_pending", lambda *args: None)
    monkeypatch.setattr(v363, "_wake_activation", lambda: None)
    assert v406._promote_same_authenticated_row("RECENT", broker, _row()) == (True, 1)
    assert calls == [("QueryOrders", {"txid": "RECENT", "trades": True})]
    assert proof[0]["broker_fill_at_epoch"] == 9990.0
    assert proof[0]["account"] == "platform:kraken"
    assert proof[0]["filled_size"] == 0.1
    assert proof[0]["filled_size_usd"] == 10.0
