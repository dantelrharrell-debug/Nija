from __future__ import annotations

import json
import types
from pathlib import Path

from bot import runtime_execution_capital_integrity_v169_patch as v169


def test_authority_fill_marker_cannot_satisfy_execution_provenance():
    ok, reason = v169._execution_provenance_valid(
        {
            "stage": "FILL_VERIFY",
            "source": "authority_heartbeat",
            "proof_kind": "authority_liveness",
        },
        "ORDER_VERIFY",
    )
    assert ok is False
    assert "execution_proof_source_invalid" in reason


def test_genuine_heartbeat_trade_fill_has_execution_provenance():
    ok, reason = v169._execution_provenance_valid(
        {
            "stage": "FILL_VERIFY",
            "source": "heartbeat_trade",
            "proof_kind": "execution_probe",
        },
        "FILL_VERIFY",
    )
    assert ok is True
    assert reason == "execution_probe_provenance_ok"


def test_authority_marker_does_not_overwrite_execution_marker(monkeypatch, tmp_path: Path):
    execution = tmp_path / "heartbeat_verified.flag"
    authority = tmp_path / "authority_heartbeat.flag"
    execution.write_text(
        json.dumps(
            {
                "stage": "FILL_VERIFY",
                "source": "heartbeat_trade",
                "proof_kind": "execution_probe",
                "verified_at_epoch": 1.0,
            }
        ),
        encoding="utf-8",
    )
    before = execution.read_text(encoding="utf-8")
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(execution))
    monkeypatch.setenv("NIJA_AUTHORITY_LIVENESS_MARKER_PATH", str(authority))

    v169._write_authority_liveness_marker(epoch_ts=123.0)

    assert execution.read_text(encoding="utf-8") == before
    payload = json.loads(authority.read_text(encoding="utf-8"))
    assert payload["stage"] == "AUTH_VERIFY"
    assert payload["proof_kind"] == "authority_liveness"


def test_prepublication_seed_uses_only_connected_platform_brokers(monkeypatch):
    calls = []

    class Broker:
        def __init__(self, broker_type: str):
            self.broker_type = broker_type

    kraken = Broker("kraken")
    coinbase = Broker("coinbase")
    manager = object()

    v164 = types.SimpleNamespace(
        _canonical_manager=lambda: manager,
        _manager_platform_mapping=lambda _manager: {
            "kraken": kraken,
            "coinbase": coinbase,
        },
        _manager_connected=lambda _manager, key, _broker: key == "kraken",
        _normalize_broker_name=lambda value: str(value).lower(),
    )
    v161 = types.SimpleNamespace(
        _guard_module=lambda: object(),
        _seed_fresh_broker_observation=lambda guard, broker_id, broker: (
            calls.append((broker_id, broker)) or True
        ),
    )

    real_import = v169.importlib.import_module

    def fake_import(name: str):
        if name == "bot.runtime_capital_publication_liveness_v164_patch":
            return v164
        if name == "bot.runtime_capital_position_convergence_v161_patch":
            return v161
        return real_import(name)

    monkeypatch.setattr(v169.importlib, "import_module", fake_import)
    attempted, seeded = v169._preseed_connected_platform_observations()

    assert (attempted, seeded) == (1, 1)
    assert calls == [("kraken", kraken)]
