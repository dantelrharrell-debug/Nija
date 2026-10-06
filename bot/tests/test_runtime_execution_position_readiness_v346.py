from __future__ import annotations

import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

import bot.runtime_execution_position_readiness_v346_patch as v346


def test_confirmed_fill_marker_requires_real_fill_fields(tmp_path, monkeypatch):
    marker = tmp_path / "heartbeat_verified.flag"
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(marker))

    import bot.runtime_execution_capital_integrity_v169_patch as v169
    import bot.runtime_confirmed_fill_profitability_v328_patch as v328

    monkeypatch.setattr(v169, "_execution_marker_path", lambda: marker)
    monkeypatch.setattr(v169, "_atomic_json_write", lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"))
    monkeypatch.setattr(v328, "_order_id", lambda result: result.get("order_id", ""))

    assert v346._write_confirmed_fill_marker(
        result={"order_id": "cb-real-1"}, symbol="BTC-USD", side="buy",
        fill_price=77000.0, filled_usd=12.35,
    ) is True
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["stage"] == "FILL_VERIFY"
    assert payload["source"] == "canonical_confirmed_fill"
    assert payload["proof_kind"] == "execution_probe"
    assert payload["order_id"] == "cb-real-1"

    marker.unlink()
    assert v346._write_confirmed_fill_marker(
        result={"order_id": ""}, symbol="BTC-USD", side="buy",
        fill_price=77000.0, filled_usd=12.35,
    ) is False
    assert not marker.exists()


def test_v169_accepts_canonical_confirmed_fill_but_not_unknown_source(monkeypatch):
    import bot.runtime_execution_capital_integrity_v169_patch as v169

    original = v169._execution_provenance_valid
    monkeypatch.setattr(v169, "_execution_provenance_valid", original)
    assert v346._patch_v169_provenance() is True

    ok, reason = v169._execution_provenance_valid(
        {"source": "canonical_confirmed_fill", "proof_kind": "execution_probe"},
        "FILL_VERIFY",
    )
    assert ok is True
    assert "canonical_confirmed_fill" in reason

    ok, _ = v169._execution_provenance_valid(
        {"source": "made_up", "proof_kind": "execution_probe"},
        "FILL_VERIFY",
    )
    assert ok is False


def test_stale_connected_platform_snapshot_is_requeued(monkeypatch):
    import bot.runtime_authoritative_position_coverage_v285_patch as v285

    broker = SimpleNamespace(connected=True)
    manager = SimpleNamespace(platform_brokers={"kraken": broker})

    monkeypatch.setattr(v285, "_platform_candidates", lambda _manager: [])
    monkeypatch.setattr(v285, "_snapshot_status", lambda _broker: (False, "stale_position_snapshot", [], 118.1, 1))
    monkeypatch.setattr(v285, "_refresh_interval_s", lambda: 49.5)
    monkeypatch.setattr(v285, "_connected", lambda _broker: True)
    monkeypatch.setattr(v285, "_label", lambda value: str(value))

    assert v346._patch_stale_platform_refresh() is True
    rows = v285._platform_candidates(manager)
    assert len(rows) == 1
    assert rows[0][0] == "kraken"
    assert rows[0][1] is broker


def test_fresh_platform_snapshot_is_not_needlessly_requeued(monkeypatch):
    import bot.runtime_authoritative_position_coverage_v285_patch as v285

    broker = SimpleNamespace(connected=True)
    manager = SimpleNamespace(platform_brokers={"kraken": broker})

    monkeypatch.setattr(v285, "_platform_candidates", lambda _manager: [])
    monkeypatch.setattr(v285, "_snapshot_status", lambda _broker: (True, "current", [], 5.0, 1))
    monkeypatch.setattr(v285, "_refresh_interval_s", lambda: 49.5)
    monkeypatch.setattr(v285, "_connected", lambda _broker: True)
    monkeypatch.setattr(v285, "_label", lambda value: str(value))

    assert v346._patch_stale_platform_refresh() is True
    assert v285._platform_candidates(manager) == []


def test_confirmed_fill_marker_uses_broker_event_time_and_does_not_refresh_same_order(tmp_path, monkeypatch):
    marker = tmp_path / "heartbeat_verified.flag"

    import bot.runtime_execution_capital_integrity_v169_patch as v169
    import bot.runtime_confirmed_fill_profitability_v328_patch as v328

    monkeypatch.setattr(v169, "_execution_marker_path", lambda: marker)
    monkeypatch.setattr(v169, "_atomic_json_write", lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"))
    monkeypatch.setattr(v328, "_order_id", lambda result: result.get("order_id", ""))

    broker_fill_epoch = 1789990000.25
    assert v346._write_confirmed_fill_marker(
        result={"order_id": "kraken-fill-1", "broker_fill_at_epoch": broker_fill_epoch},
        symbol="ETHUSD:BTNL",
        side="sell",
        fill_price=2482.0999915373,
        filled_usd=341.10763,
    ) is True

    first = json.loads(marker.read_text(encoding="utf-8"))
    assert first["version"] == 4
    assert first["verified_at_epoch"] == broker_fill_epoch

    assert v346._write_confirmed_fill_marker(
        result={"order_id": "kraken-fill-1", "broker_fill_at_epoch": broker_fill_epoch + 999.0},
        symbol="ETHUSD:BTNL",
        side="sell",
        fill_price=2482.0999915373,
        filled_usd=341.10763,
    ) is True

    second = json.loads(marker.read_text(encoding="utf-8"))
    assert second["verified_at_epoch"] == broker_fill_epoch
    assert second == first


def test_legacy_v3_same_order_marker_is_migrated_to_broker_event_time(tmp_path, monkeypatch):
    marker = tmp_path / "heartbeat_verified.flag"

    import bot.runtime_execution_capital_integrity_v169_patch as v169
    import bot.runtime_confirmed_fill_profitability_v328_patch as v328

    marker.write_text(json.dumps({
        "verified": True,
        "version": 3,
        "source": "canonical_confirmed_fill",
        "proof_kind": "execution_probe",
        "order_id": "kraken-old-replayed",
        "verified_at_epoch": 9999999999.0,
    }), encoding="utf-8")
    monkeypatch.setattr(v169, "_execution_marker_path", lambda: marker)
    monkeypatch.setattr(v169, "_atomic_json_write", lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"))
    monkeypatch.setattr(v328, "_order_id", lambda result: result.get("order_id", ""))

    broker_fill_epoch = 1789980000.5
    assert v346._write_confirmed_fill_marker(
        result={"order_id": "kraken-old-replayed", "broker_fill_at_epoch": broker_fill_epoch},
        symbol="ETHUSD:BTNL",
        side="sell",
        fill_price=2482.0999915373,
        filled_usd=341.10763,
    ) is True

    migrated = json.loads(marker.read_text(encoding="utf-8"))
    assert migrated["version"] == 4
    assert migrated["verified_at_epoch"] == broker_fill_epoch


def test_recovered_fill_without_authenticated_event_time_cannot_write_execution_proof(tmp_path, monkeypatch):
    marker = tmp_path / "heartbeat_verified.flag"

    import bot.runtime_execution_capital_integrity_v169_patch as v169
    import bot.runtime_confirmed_fill_profitability_v328_patch as v328

    monkeypatch.setattr(v169, "_execution_marker_path", lambda: marker)
    monkeypatch.setattr(v169, "_atomic_json_write", lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"))
    monkeypatch.setattr(v328, "_order_id", lambda result: result.get("order_id", ""))

    assert v346._write_confirmed_fill_marker(
        result={
            "order_id": "kraken-recovered-no-time",
            "kraken_trade_history_reconciled": True,
            "recovered_fill_proof": True,
        },
        symbol="ETHUSD:BTNL",
        side="sell",
        fill_price=2482.0999915373,
        filled_usd=341.10763,
    ) is False

    assert not marker.exists()


def test_restart_recovery_uses_authenticated_fresh_fill_without_order(monkeypatch):
    now = 1791247000.0
    broker = SimpleNamespace(account_type="platform", connected=True, broker_type="kraken")

    monkeypatch.setattr(v346.time, "time", lambda: now)
    monkeypatch.setattr(v346, "_current_execution_marker_ready", lambda: (False, "marker_missing"))
    monkeypatch.setattr(v346, "_writer_epoch_for_recovery", lambda: (True, "777"))
    monkeypatch.setattr(v346, "_canonical_kraken_broker", lambda: broker)
    monkeypatch.setattr(v346, "_recovery_freshness_s", lambda: 1800.0)
    monkeypatch.setattr(v346, "_recovery_interval_s", lambda: 10.0)
    monkeypatch.setattr(v346, "_RECOVERY_LAST_ATTEMPT_MONO", 0.0)
    monkeypatch.setattr(v346, "_RECOVERY_LAST_GENERATION", "")
    monkeypatch.setattr(v346.time, "monotonic", lambda: 1000.0)

    v357 = ModuleType("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
    v357._private_read = lambda _broker, method, params: {
        "error": [],
        "result": {"trades": {
            "T1": {
                "ordertxid": "ORDER-1",
                "time": now - 30.0,
                "type": "buy",
                "pair": "XXBTZUSD",
            }
        }},
    } if method == "TradesHistory" else {}
    v357._query_order_row = lambda _broker, oid: {
        "status": "closed", "vol_exec": "0.001", "cost": "85.0"
    } if oid == "ORDER-1" else {}
    v357._query_order_fill = lambda row: ("closed", 85000.0, 0.001, 85.0)
    v357._trade_history_fill = lambda *args, **kwargs: (85000.0, 0.001, 85.0, 1, now - 30.0)
    monkeypatch.setitem(__import__("sys").modules, "bot.runtime_kraken_delayed_fill_reconciliation_v357_patch", v357)

    v328 = __import__("bot.runtime_confirmed_fill_profitability_v328_patch", fromlist=["x"])
    monkeypatch.setattr(v328, "_normalize_dict_fill", lambda result, *, symbol, side: (
        v346._write_confirmed_fill_marker(
            result=result, symbol=symbol, side=side,
            fill_price=float(result["filled_price"]),
            filled_usd=float(result["filled_size_usd"]),
        ) and (float(result["filled_price"]), float(result["filled_size_usd"]))
    ) or (0.0, 0.0))

    state = {"ready": False}
    original_write = v346._write_confirmed_fill_marker

    def write_and_mark(**kwargs):
        ok = original_write(**kwargs)
        state["ready"] = bool(ok)
        return ok

    monkeypatch.setattr(v346, "_write_confirmed_fill_marker", write_and_mark)
    monkeypatch.setattr(
        v346,
        "_current_execution_marker_ready",
        lambda: (state["ready"], "current:canonical_confirmed_fill" if state["ready"] else "marker_missing"),
    )
    monkeypatch.setattr(v346, "_wake_activation_after_proof", lambda: None)

    import bot.runtime_execution_capital_integrity_v169_patch as v169
    import bot.runtime_confirmed_fill_profitability_v328_patch as real_v328
    marker = Path("/tmp/test_restart_execution_proof.json")
    if marker.exists():
        marker.unlink()
    monkeypatch.setattr(v169, "_execution_marker_path", lambda: marker)
    monkeypatch.setattr(v169, "_atomic_json_write", lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"))
    monkeypatch.setattr(real_v328, "_order_id", lambda result: result.get("order_id", ""))

    ok, detail = v346._recover_recent_kraken_execution_proof()
    assert ok is True
    assert detail == "current:canonical_confirmed_fill"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["order_id"] == "ORDER-1"
    assert payload["verified_at_epoch"] == now - 30.0
    marker.unlink()


def test_restart_recovery_rejects_stale_fill(monkeypatch):
    now = 1791247000.0
    broker = SimpleNamespace(account_type="platform", connected=True, broker_type="kraken")
    monkeypatch.setattr(v346.time, "time", lambda: now)
    monkeypatch.setattr(v346, "_current_execution_marker_ready", lambda: (False, "marker_missing"))
    monkeypatch.setattr(v346, "_writer_epoch_for_recovery", lambda: (True, "777"))
    monkeypatch.setattr(v346, "_canonical_kraken_broker", lambda: broker)
    monkeypatch.setattr(v346, "_recovery_freshness_s", lambda: 1800.0)
    monkeypatch.setattr(v346, "_recovery_interval_s", lambda: 10.0)
    monkeypatch.setattr(v346, "_RECOVERY_LAST_ATTEMPT_MONO", 0.0)
    monkeypatch.setattr(v346, "_RECOVERY_LAST_GENERATION", "")
    monkeypatch.setattr(v346.time, "monotonic", lambda: 1000.0)

    v357 = ModuleType("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
    v357._private_read = lambda _broker, method, params: {
        "error": [],
        "result": {"trades": {
            "T1": {
                "ordertxid": "OLD-ORDER",
                "time": now - 7200.0,
                "type": "buy",
                "pair": "XXBTZUSD",
            }
        }},
    }
    v357._query_order_row = lambda *_args: {"status": "closed", "vol_exec": "0.001", "cost": "85.0"}
    v357._query_order_fill = lambda row: ("closed", 85000.0, 0.001, 85.0)
    v357._trade_history_fill = lambda *args, **kwargs: (85000.0, 0.001, 85.0, 1, now - 7200.0)
    monkeypatch.setitem(__import__("sys").modules, "bot.runtime_kraken_delayed_fill_reconciliation_v357_patch", v357)

    ok, detail = v346._recover_recent_kraken_execution_proof()
    assert ok is False
    assert detail == "no_fresh_final_exact_kraken_fill"
