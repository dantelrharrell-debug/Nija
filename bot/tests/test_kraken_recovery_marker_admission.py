"""Authenticated account ownership and durable deferred-fill admission regressions."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from bot import runtime_execution_position_readiness_v346_patch as v346
from bot import runtime_kraken_delayed_fill_reconciliation_v357_patch as v357
from bot import runtime_kraken_deferred_fill_proof_recovery_v363_patch as v363


class KrakenBroker:
    broker_type = "kraken"
    connected = True

    def _kraken_private_call(self, method, params=None, **kwargs):
        return {"error": [], "result": {"ORDER": {
            "status": "closed", "vol_exec": "0.01", "cost": "25", "closetm": 9995.0,
        }}}


@pytest.fixture
def context(tmp_path, monkeypatch):
    from bot import runtime_execution_capital_integrity_v169_patch as v169
    from bot import runtime_confirmed_fill_profitability_v328_patch as v328
    broker = KrakenBroker()
    manager = SimpleNamespace(platform_brokers={"kraken": broker}, user_brokers={})
    module = SimpleNamespace(get_broker_manager=lambda: manager)
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", module)
    marker = tmp_path / "proof.json"
    monkeypatch.setattr(v169, "_execution_marker_path", lambda: marker)
    monkeypatch.setattr(v169, "_atomic_json_write", lambda path, payload: path.write_text(json.dumps(payload)))
    monkeypatch.setattr(v328, "_order_id", lambda result: result.get("order_id", ""))
    monkeypatch.setattr(v346.time, "time", lambda: 10000.0)
    monkeypatch.setenv("NIJA_KRAKEN_PENDING_FILL_PROOF_PATH", str(tmp_path / "pending.json"))
    monkeypatch.setattr(v363, "_kraken_brokers", lambda: [broker])
    normalize = lambda result, **kwargs: (result["filled_price"], result["filled_size_usd"])
    monkeypatch.setattr(v363, "_v328", lambda: SimpleNamespace(_normalize_dict_fill=normalize))
    wakes = []
    monkeypatch.setattr(v363, "_wake_activation", lambda: wakes.append(True))
    return broker, manager, marker, wakes


def test_exact_platform_broker_scope_reaches_durable_marker(context):
    broker, manager, marker, wakes = context
    v363.record_pending_order(order_id="ORDER", symbol="ETH-USD", side="buy")
    assert v363.recover_once() == 1
    payload = json.loads(marker.read_text())
    assert payload["broker"] == "kraken"
    assert payload["account"] == payload["account_id"] == "platform:kraken"
    assert payload["verified_at_epoch"] == 9995.0
    assert payload["recovered_fill_proof"] is True
    assert v363._load_pending() == {}
    assert wakes == [True]


@pytest.mark.parametrize("registration", ["user", "unknown", "shared", "wrong_venue"])
def test_unknown_user_or_ambiguous_owner_cannot_satisfy_platform_proof(context, registration):
    broker, manager, marker, wakes = context
    if registration != "shared":
        manager.platform_brokers = {}
    if registration in {"user", "shared"}:
        manager.user_brokers = {"user-a": {"kraken": broker}}
    if registration == "wrong_venue":
        manager.platform_brokers = {"coinbase": broker}
    enriched = v357._enrich_kraken_final_order(
        broker, {"order_id": "ORDER", "status": "closed", "account": "platform:kraken",
                 "account_id": "platform:kraken"}, symbol="ETH-USD", side="buy",
    )
    assert enriched["account"] == enriched["account_id"] == ""
    v363.record_pending_order(order_id="ORDER", symbol="ETH-USD", side="buy")
    assert v363.recover_once() == 0
    assert "ORDER" in v363._load_pending()
    assert not marker.exists()
    assert wakes == []


def test_failed_durable_write_retains_pending_order(context, monkeypatch):
    broker, manager, marker, wakes = context
    assert v363._patch_v357_enrichment()
    monkeypatch.setattr(v346, "_write_confirmed_fill_marker", lambda **kwargs: False)
    v363.record_pending_order(order_id="ORDER", symbol="ETH-USD", side="buy")
    assert v363.recover_once() == 0
    assert "ORDER" in v363._load_pending()
    assert not marker.exists()
    assert wakes == []


def _write_event(order_id, epoch):
    return v346._write_confirmed_fill_marker(
        result={"order_id": order_id, "broker_fill_at_epoch": epoch, "recovered_fill_proof": True,
                "broker": "kraken", "account": "platform:kraken", "account_id": "platform:kraken"},
        symbol="ETH-USD", side="buy", fill_price=2500.0, filled_usd=25.0,
    )


def test_older_different_order_cannot_replace_newer_execution_evidence(context):
    _, _, marker, _ = context
    assert _write_event("NEWER", 9999.0)
    before = marker.read_bytes()
    assert not _write_event("OLDER", 9000.0)
    assert marker.read_bytes() == before


def test_same_order_migration_still_corrects_observation_time(context):
    _, _, marker, _ = context
    assert _write_event("ORDER", 9999.0)
    assert _write_event("ORDER", 9000.0)
    assert json.loads(marker.read_text())["verified_at_epoch"] == 9000.0


def test_concurrent_recoveries_preserve_latest_broker_event(context):
    _, _, marker, _ = context
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda epoch: _write_event(str(epoch), float(epoch)), [9998, 9000, 9999, 9500]))
    assert json.loads(marker.read_text())["verified_at_epoch"] == 9999.0
