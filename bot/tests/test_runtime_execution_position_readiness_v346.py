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
