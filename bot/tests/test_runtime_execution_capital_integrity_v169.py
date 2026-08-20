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


def test_detached_authority_module_is_repaired(monkeypatch, tmp_path: Path):
    """A stale thread-owned module object must not keep writing execution proof."""
    execution = tmp_path / "heartbeat_verified.flag"
    authority = tmp_path / "authority_heartbeat.flag"
    execution.write_text("sentinel", encoding="utf-8")
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(execution))
    monkeypatch.setenv("NIJA_AUTHORITY_LIVENESS_MARKER_PATH", str(authority))

    detached = types.ModuleType("authority_heartbeat")
    detached.__file__ = "/detached/authority_heartbeat.py"
    detached._DEFAULT_MARKER_STAGE = "FILL_VERIFY"

    def legacy_write() -> None:
        execution.write_text(
            json.dumps(
                {
                    "stage": "FILL_VERIFY",
                    "source": "authority_heartbeat",
                }
            ),
            encoding="utf-8",
        )

    detached._write_heartbeat_marker = legacy_write

    assert any(
        module is detached
        for module in v169._module_candidates(
            "bot.authority_heartbeat",
            "authority_heartbeat",
        )
    )
    assert v169._patch_authority_heartbeat_writer() is True

    detached._write_heartbeat_marker()

    assert execution.read_text(encoding="utf-8") == "sentinel"
    payload = json.loads(authority.read_text(encoding="utf-8"))
    assert payload["stage"] == "AUTH_VERIFY"
    assert payload["proof_kind"] == "authority_liveness"
    assert detached._DEFAULT_MARKER_STAGE == "AUTH_VERIFY"


def test_detached_trading_strategy_gets_execution_provenance(monkeypatch, tmp_path: Path):
    execution = tmp_path / "heartbeat_verified.flag"
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(execution))

    detached = types.ModuleType("trading_strategy")
    detached.__file__ = "/detached/trading_strategy.py"

    class TradingStrategy:
        def _persist_heartbeat_marker(self, *, stage: str, details=None) -> None:
            execution.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "verified_at_epoch": 1.0,
                        "details": details or {},
                    }
                ),
                encoding="utf-8",
            )

    detached.TradingStrategy = TradingStrategy

    assert v169._patch_trading_strategy_provenance() is True
    TradingStrategy()._persist_heartbeat_marker(stage="ORDER_VERIFY", details={"ok": True})

    payload = json.loads(execution.read_text(encoding="utf-8"))
    assert payload["source"] == "heartbeat_trade"
    assert payload["proof_kind"] == "execution_probe"


def test_detached_tsm_still_rejects_authority_execution_proof(monkeypatch, tmp_path: Path):
    execution = tmp_path / "heartbeat_verified.flag"
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(execution))
    execution.write_text(
        json.dumps(
            {
                "stage": "FILL_VERIFY",
                "verified_at_epoch": 1.0,
                "source": "authority_heartbeat",
                "proof_kind": "authority_liveness",
            }
        ),
        encoding="utf-8",
    )

    detached = types.ModuleType("trading_state_machine")
    detached.__file__ = "/detached/trading_state_machine.py"

    def heartbeat_status():
        return True, "", {"required_stage": "ORDER_VERIFY", "stage": "FILL_VERIFY"}

    detached._heartbeat_verification_status = heartbeat_status

    assert v169._patch_tsm_execution_provenance() is True
    ok, reason, meta = detached._heartbeat_verification_status()

    assert ok is False
    assert "execution_proof_source_invalid" in reason
    assert meta["source"] == "authority_heartbeat"
    assert meta["proof_kind"] == "authority_liveness"


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
