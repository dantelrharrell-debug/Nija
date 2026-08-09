from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PATCH_PATH = Path(__file__).resolve().parents[1] / "activation_snapshot_bridge_patch.py"
spec = importlib.util.spec_from_file_location("activation_bridge_v63_under_test", PATCH_PATH)
assert spec and spec.loader
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


def _meta(*, accepted: bool = True) -> tuple[bool, dict]:
    return accepted, {
        "ca_available": True,
        "accepted_latch": False,
        "hydrated": True,
        "stale": False,
        "real_capital": 240.07922691659326,
        "valid_brokers": 2,
        "brokers_ready": True,
        "conditions_met": True,
    }


def test_augment_cycle_capital_promotes_real_authority_snapshot():
    snapshot = {
        "ca_is_hydrated": False,
        "ca_total_capital": 0.0,
        "ca_valid_brokers": 0,
        "snapshot_source": "placeholder",
        "aggregation_normalized": True,
        "sync_failed": True,
    }

    bridged = bridge._augment_cycle_capital(snapshot, _meta()[1])

    assert bridged["ca_is_hydrated"] is True
    assert bridged["ca_total_capital"] == 240.07922691659326
    assert bridged["ca_valid_brokers"] == 2
    assert bridged["snapshot_source"] == "capital_authority"
    assert bridged["is_post_hydration"] is True
    assert bridged["mabm_brokers_ready"] is True
    assert bridged["sync_failed"] is False
    assert bridge._cycle_capital_live(bridged) is True


def test_augment_preserves_explicit_aggregation_failure():
    snapshot = {
        "ca_is_hydrated": False,
        "ca_total_capital": 0.0,
        "ca_valid_brokers": 0,
        "snapshot_source": "placeholder",
        "aggregation_normalized": False,
    }

    bridged = bridge._augment_cycle_capital(snapshot, _meta()[1])

    assert bridged["aggregation_normalized"] is False
    assert bridged["ca_valid_brokers"] == 2


def test_cycle_capital_live_rejects_placeholder_and_sync_failure():
    assert bridge._cycle_capital_live({}) is False
    assert bridge._cycle_capital_live(
        {
            "ca_is_hydrated": True,
            "ca_total_capital": 240.08,
            "ca_valid_brokers": 2,
            "snapshot_source": "placeholder",
            "sync_failed": False,
        }
    ) is False
    assert bridge._cycle_capital_live(
        {
            "ca_is_hydrated": True,
            "ca_total_capital": 240.08,
            "ca_valid_brokers": 2,
            "snapshot_source": "capital_authority",
            "sync_failed": True,
        }
    ) is False


def test_direct_scan_wrapper_temporarily_bridges_and_restores(monkeypatch):
    module_name = "v63_fake_core_module"
    fake_module = types.ModuleType(module_name)
    original_capital = {
        "ca_is_hydrated": False,
        "ca_total_capital": 0.0,
        "ca_valid_brokers": 0,
        "snapshot_source": "placeholder",
        "aggregation_normalized": True,
        "sync_failed": True,
    }
    fake_module._current_cycle_capital = original_capital
    fake_module._current_cycle_id = ""

    observed = {}

    class FakeCore:
        __module__ = module_name

        def run_scan_phase(self, *args, **kwargs):
            observed["capital"] = dict(fake_module._current_cycle_capital)
            observed["cycle_id"] = fake_module._current_cycle_id
            return "scan-result"

    fake_module.NijaCoreLoop = FakeCore
    sys.modules[module_name] = fake_module
    monkeypatch.setattr(bridge, "_capital_snapshot_meta", lambda: _meta())

    try:
        assert bridge._patch_core_loop_class(FakeCore) is True
        result = FakeCore().run_scan_phase()
    finally:
        sys.modules.pop(module_name, None)

    assert result == "scan-result"
    assert observed["capital"]["ca_is_hydrated"] is True
    assert observed["capital"]["ca_total_capital"] == 240.07922691659326
    assert observed["capital"]["ca_valid_brokers"] == 2
    assert observed["capital"]["snapshot_source"] == "capital_authority"
    assert observed["cycle_id"].endswith("-direct-v63")
    assert fake_module._current_cycle_capital is original_capital
    assert fake_module._current_cycle_id == ""


def test_direct_scan_wrapper_does_not_bridge_unaccepted_capital(monkeypatch):
    module_name = "v63_fake_core_unaccepted"
    fake_module = types.ModuleType(module_name)
    original_capital = {
        "ca_is_hydrated": False,
        "ca_total_capital": 0.0,
        "ca_valid_brokers": 0,
        "snapshot_source": "placeholder",
    }
    fake_module._current_cycle_capital = original_capital
    fake_module._current_cycle_id = "original-cycle"

    observed = {}

    class FakeCore:
        __module__ = module_name

        def run_scan_phase(self, *args, **kwargs):
            observed["capital"] = fake_module._current_cycle_capital
            observed["cycle_id"] = fake_module._current_cycle_id
            return "unchanged"

    fake_module.NijaCoreLoop = FakeCore
    sys.modules[module_name] = fake_module
    monkeypatch.setattr(bridge, "_capital_snapshot_meta", lambda: _meta(accepted=False))

    try:
        assert bridge._patch_core_loop_class(FakeCore) is True
        result = FakeCore().run_scan_phase()
    finally:
        sys.modules.pop(module_name, None)

    assert result == "unchanged"
    assert observed["capital"] is original_capital
    assert observed["cycle_id"] == "original-cycle"
