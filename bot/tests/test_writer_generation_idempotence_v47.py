from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PATCH_PATH = Path(__file__).resolve().parents[1] / "writer_generation_idempotence_v47_patch.py"
spec = importlib.util.spec_from_file_location("nija_test_writer_generation_idempotence_v47", PATCH_PATH)
assert spec is not None and spec.loader is not None
v47 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v47)


def fake_v45(generation=3337, proof_ok=True):
    module = types.ModuleType("nija_writer_generation_handoff_v45_prebot")
    module._HEARTBEAT_PATCH = "_v45_hb"
    module._prove_process_writer = lambda: ({"generation": generation}, "") if proof_ok else (None, "no_proof")

    def patch_hb(target):
        cls = target.AuthorityHeartbeatMonitor

        def hb(self):
            return None

        hb._v45_hb = True
        cls._write_heartbeat_to_redis = hb
        return True

    module._patch_heartbeat_module = patch_hb
    module._patch_scope_module = lambda _scope: True
    return module


def fake_scope(counter):
    module = types.ModuleType("authority_heartbeat_generation_scope_patch")
    module._platform_generation = lambda: (10, "")

    def legacy(target):
        counter[0] += 1

        def legacy_hb(self):
            return None

        target.AuthorityHeartbeatMonitor._write_heartbeat_to_redis = legacy_hb
        return True

    module._patch_module = legacy
    return module


def fake_target():
    module = types.ModuleType("bot.authority_heartbeat")

    class Monitor:
        def _write_heartbeat_to_redis(self):
            return None

    module.AuthorityHeartbeatMonitor = Monitor
    return module


def test_scope_wrapper_stops_legacy_ping_pong():
    count = [0]
    v45 = fake_v45()
    scope = fake_scope(count)
    target = fake_target()
    assert v47._converge_scope_module(v45, scope)
    assert scope._patch_module(target)
    first = target.AuthorityHeartbeatMonitor._write_heartbeat_to_redis
    assert getattr(first, "_v45_hb", False)
    assert count[0] == 1
    assert scope._patch_module(target)
    assert target.AuthorityHeartbeatMonitor._write_heartbeat_to_redis is first
    assert count[0] == 1


def test_converge_scope_is_idempotent():
    count = [0]
    v45 = fake_v45()
    scope = fake_scope(count)
    assert v47._converge_scope_module(v45, scope)
    generation_fn = scope._platform_generation
    patch_fn = scope._patch_module
    assert v47._converge_scope_module(v45, scope)
    assert scope._platform_generation is generation_fn
    assert scope._patch_module is patch_fn


def test_stable_v45_scope_patcher_does_not_recreate_wrappers():
    count = [0]
    v45 = fake_v45()
    scope = fake_scope(count)
    assert v47._patch_v45_module(v45)
    patcher = v45._patch_scope_module
    assert patcher(scope)
    generation_fn = scope._platform_generation
    scope_patch = scope._patch_module
    assert patcher(scope)
    assert v45._patch_scope_module is patcher
    assert scope._platform_generation is generation_fn
    assert scope._patch_module is scope_patch


def test_generation_uses_v45_process_writer_proof():
    v45 = fake_v45(4444)
    assert v47._process_generation(v45) == (4444, "")


def test_generation_fails_closed_without_proof():
    v45 = fake_v45(proof_ok=False)
    assert v47._process_generation(v45) == (0, "no_proof")


def test_reconcile_patches_loaded_aliases(monkeypatch):
    count = [0]
    v45 = fake_v45()
    scope = fake_scope(count)
    monkeypatch.setitem(sys.modules, "nija_writer_generation_handoff_v45_prebot", v45)
    monkeypatch.setitem(sys.modules, "authority_heartbeat_generation_scope_patch", scope)
    state = v47.reconcile_once()
    assert state["ready"] is True
    assert getattr(v45._patch_scope_module, v47._V45_PATCHER_MARK, False)
    assert getattr(scope._patch_module, v47._SCOPE_WRAPPER_MARK, False)
