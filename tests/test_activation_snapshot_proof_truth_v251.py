from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path


PATCH = Path(__file__).resolve().parents[1] / "bot" / "runtime_activation_snapshot_proof_truth_v251_patch.py"
spec = importlib.util.spec_from_file_location("activation_snapshot_proof_truth_v251_under_test", PATCH)
assert spec and spec.loader
v251 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v251
spec.loader.exec_module(v251)


def test_readiness_incomplete_blocks_bridge_fallback(monkeypatch):
    readiness = types.ModuleType("bot.readiness_table")
    readiness.snapshot = lambda: {
        "broker_connected": True,
        "capital_ready": True,
        "authority_ready": True,
        "nonce_ready": True,
        "execution_ready": False,
    }
    monkeypatch.setitem(sys.modules, "bot.readiness_table", readiness)
    monkeypatch.setitem(sys.modules, "readiness_table", readiness)

    bridge = types.ModuleType("bot.activation_snapshot_bridge_patch")
    bridge._concrete_activation_gates_pass = lambda _tsm: (True, "")
    monkeypatch.setitem(sys.modules, "bot.activation_snapshot_bridge_patch", bridge)
    monkeypatch.setitem(sys.modules, "activation_snapshot_bridge_patch", bridge)

    tsm = types.SimpleNamespace(_heartbeat_verification_status=lambda: (True, "", {}))
    monkeypatch.setenv("HEARTBEAT_TRADE", "true")

    assert v251._patch_bridge() is True
    ok, detail = bridge._concrete_activation_gates_pass(tsm)

    assert ok is False
    assert detail == "readiness_incomplete:execution_ready"


def test_missing_genuine_heartbeat_marker_blocks_fallback(monkeypatch):
    readiness = types.ModuleType("bot.readiness_table")
    readiness.snapshot = lambda: {
        "broker_connected": True,
        "capital_ready": True,
        "authority_ready": True,
        "nonce_ready": True,
        "execution_ready": True,
    }
    monkeypatch.setitem(sys.modules, "bot.readiness_table", readiness)
    monkeypatch.setitem(sys.modules, "readiness_table", readiness)

    bridge = types.ModuleType("bot.activation_snapshot_bridge_patch")
    bridge._concrete_activation_gates_pass = lambda _tsm: (True, "")
    monkeypatch.setitem(sys.modules, "bot.activation_snapshot_bridge_patch", bridge)
    monkeypatch.setitem(sys.modules, "activation_snapshot_bridge_patch", bridge)

    tsm = types.SimpleNamespace(
        _heartbeat_verification_status=lambda: (False, "marker_missing", {"required_stage": "ORDER_VERIFY"})
    )
    monkeypatch.setenv("HEARTBEAT_REQUIRED_FIRST_ACTIVATION", "true")

    assert v251._patch_bridge() is True
    ok, detail = bridge._concrete_activation_gates_pass(tsm)

    assert ok is False
    assert detail == "heartbeat_verification:marker_missing"


def test_complete_readiness_and_genuine_heartbeat_allow_existing_compat_route(monkeypatch):
    readiness = types.ModuleType("bot.readiness_table")
    readiness.snapshot = lambda: {
        "broker_connected": True,
        "capital_ready": True,
        "authority_ready": True,
        "nonce_ready": True,
        "execution_ready": True,
    }
    monkeypatch.setitem(sys.modules, "bot.readiness_table", readiness)
    monkeypatch.setitem(sys.modules, "readiness_table", readiness)

    bridge = types.ModuleType("bot.activation_snapshot_bridge_patch")
    bridge._concrete_activation_gates_pass = lambda _tsm: (True, "")
    monkeypatch.setitem(sys.modules, "bot.activation_snapshot_bridge_patch", bridge)
    monkeypatch.setitem(sys.modules, "activation_snapshot_bridge_patch", bridge)

    tsm = types.SimpleNamespace(
        _heartbeat_verification_status=lambda: (
            True,
            "",
            {"stage": "ORDER_VERIFY", "verified_at_epoch": 123.0},
        )
    )
    monkeypatch.setenv("HEARTBEAT_TRADE", "true")

    assert v251._patch_bridge() is True
    ok, detail = bridge._concrete_activation_gates_pass(tsm)

    assert ok is True
    assert detail == "canonical_readiness_and_heartbeat_proof_current"


def test_v251_does_not_fabricate_activation_or_proof():
    source = PATCH.read_text(encoding="utf-8")
    forbidden = (
        "force_activate_bypass(",
        "_force_live_active_transition(",
        "execution_ready\"] = True",
        "nonce_ready\"] = True",
        "heartbeat_verified.flag\").write",
        "get_kill_switch().deactivate(",
    )
    assert all(token not in source for token in forbidden)
    assert "execution_proof_fabricated=false" in source
    assert "heartbeat_marker_written=false" in source
    assert "forced_activation=false" in source
    assert "safety_gates_bypassed=false" in source
