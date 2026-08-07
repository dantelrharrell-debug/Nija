from __future__ import annotations

import builtins
import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType


BOT_DIR = Path(__file__).resolve().parents[1]
PATCH_PATH = BOT_DIR / "heartbeat_authority_identity_v38_patch.py"
STATE_PATH = BOT_DIR / "heartbeat_state.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _reset_shared_state(patch: ModuleType) -> None:
    for key in (patch._STATE_KEY, patch._STATE_LOCK_KEY):
        if hasattr(builtins, key):
            delattr(builtins, key)


def test_duplicate_heartbeat_imports_share_one_state(monkeypatch):
    patch = _load("heartbeat_identity_v38_test", PATCH_PATH)
    _reset_shared_state(patch)

    first = _load("heartbeat_state_copy_a", STATE_PATH)
    second = _load("heartbeat_state_copy_b", STATE_PATH)
    assert first is not second

    assert patch._patch_heartbeat_state(first) is True
    state_a = first.get_heartbeat_state()
    state_a.record_heartbeat(generation=77)

    assert patch._patch_heartbeat_state(second) is True
    state_b = second.get_heartbeat_state()

    assert state_a is state_b
    healthy, age_s, authoritative, _ts = state_b.health_for_generation(
        expected_generation=77,
        max_age_s=120.0,
    )
    assert authoritative is True
    assert healthy is True
    assert age_s < 1.0
    assert sys.modules["bot.heartbeat_state"] is second
    assert sys.modules["heartbeat_state"] is second


def test_generation_reader_cannot_report_inf_after_shared_success(monkeypatch):
    patch = _load("heartbeat_identity_v38_generation_test", PATCH_PATH)
    _reset_shared_state(patch)
    state_module = _load("heartbeat_state_generation_copy", STATE_PATH)
    patch._patch_heartbeat_state(state_module)

    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", "120")
    state_module.get_heartbeat_state().record_heartbeat(generation=3)

    proof = patch._canonical_heartbeat_proof(3)
    assert proof["authoritative"] is True
    assert proof["healthy"] is True
    assert proof["age_s"] < 1.0


def test_reentry_proof_uses_canonical_monotonic_heartbeat_not_stale_env(monkeypatch):
    patch = _load("heartbeat_identity_v38_reentry_test", PATCH_PATH)
    _reset_shared_state(patch)
    state_module = _load("heartbeat_state_reentry_copy", STATE_PATH)
    patch._patch_heartbeat_state(state_module)
    state_module.get_heartbeat_state().record_heartbeat(generation=42)

    monkeypatch.setenv("NIJA_REDIS_URL", "redis://configured")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "tok-42")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "42")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    # This old wall-clock value reproduced the legacy recursion-guard failure.
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", str(time.time() - 999.0))

    class Runtime:
        acquired = True
        lost = False

        def _nija_lease_renewal_health(self):
            return True, "renewal_healthy", 1.0, 60.0

    entrypoint = ModuleType("bot.entrypoint_writer_authority")
    entrypoint.get_entrypoint_writer_authority = lambda: Runtime()
    sys.modules["bot.entrypoint_writer_authority"] = entrypoint

    recursion = ModuleType("bot.writer_authority_recursion_guard_patch")
    recursion._writer_reentry_proof = lambda: {"ok": False}
    assert patch._patch_recursion_guard(recursion) is True

    proof = recursion._writer_reentry_proof()
    assert proof["ok"] is True
    assert proof["redis_reachable"] is True
    assert proof["heartbeat_authoritative"] is True
    assert proof["heartbeat_healthy"] is True
    assert proof["renewal_ok"] is True
    assert proof["heartbeat_age_s"] < 1.0


def test_reentry_proof_still_fails_closed_when_renewal_is_unhealthy(monkeypatch):
    patch = _load("heartbeat_identity_v38_failclosed_test", PATCH_PATH)
    _reset_shared_state(patch)
    state_module = _load("heartbeat_state_failclosed_copy", STATE_PATH)
    patch._patch_heartbeat_state(state_module)
    state_module.get_heartbeat_state().record_heartbeat(generation=9)

    monkeypatch.setenv("NIJA_REDIS_URL", "redis://configured")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "tok-9")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")

    class Runtime:
        acquired = True
        lost = False

        def _nija_lease_renewal_health(self):
            return False, "renewal_stale", 90.0, 60.0

    entrypoint = ModuleType("bot.entrypoint_writer_authority")
    entrypoint.get_entrypoint_writer_authority = lambda: Runtime()
    sys.modules["bot.entrypoint_writer_authority"] = entrypoint

    recursion = ModuleType("bot.writer_authority_recursion_guard_patch")
    recursion._writer_reentry_proof = lambda: {"ok": True}
    patch._patch_recursion_guard(recursion)

    proof = recursion._writer_reentry_proof()
    assert proof["ok"] is False
    assert proof["redis_reachable"] is False
    assert proof["renewal_ok"] is False
