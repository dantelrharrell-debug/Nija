from __future__ import annotations

import importlib
import time

import pytest

from bot.heartbeat_state import reset_heartbeat_state_for_testing
from bot.heartbeat_authority_single_source_patch import (
    _patch_runtime_authority_convergence,
    heartbeat_max_age_s,
)


@pytest.fixture(autouse=True)
def _reset_heartbeat(monkeypatch: pytest.MonkeyPatch):
    reset_heartbeat_state_for_testing()
    for name in (
        "NIJA_WRITER_LEASE_ACQUIRED",
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_LEASE_GENERATION",
        "NIJA_WRITER_GENERATION",
        "NIJA_WRITER_HEARTBEAT_ACTIVE",
        "NIJA_CORE_THREAD_ALIVE",
        "KRAKEN_NONCE_LEASE_REQUIRED",
        "NIJA_WRITER_HEARTBEAT_MAX_AGE_S",
        "NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_heartbeat_state_for_testing()


def _seed_runtime(monkeypatch: pytest.MonkeyPatch, generation: int = 77) -> None:
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", str(generation))
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_CORE_THREAD_ALIVE", "1")
    monkeypatch.setenv("KRAKEN_NONCE_LEASE_REQUIRED", "0")


def test_single_policy_overrides_legacy_90_second_knob(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", "120")
    monkeypatch.setenv("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S", "90")

    assert heartbeat_max_age_s() == 120.0
    assert (
        __import__("os").environ["NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S"]
        == "120.0"
    )


def test_runtime_convergence_uses_monotonic_canonical_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
):
    generation = 77
    _seed_runtime(monkeypatch, generation)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", "120")
    monkeypatch.setenv("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S", "5")

    state = reset_heartbeat_state_for_testing()
    state.record_heartbeat(
        generation=generation,
        timestamp=1.0,
        monotonic_timestamp=time.monotonic(),
    )

    module = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
    _patch_runtime_authority_convergence(module)

    # A wildly different wall clock must not make a fresh heartbeat stale.
    monkeypatch.setattr(module.time, "time", lambda: 10**12)
    ok, detail = module._heartbeat_ready()

    assert ok is True
    assert detail.startswith("heartbeat_ready")
    assert "generation=77" in detail


def test_runtime_convergence_rejects_wrong_generation(monkeypatch: pytest.MonkeyPatch):
    _seed_runtime(monkeypatch, generation=88)
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", "120")

    state = reset_heartbeat_state_for_testing()
    state.record_heartbeat(generation=77)

    module = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
    # Clear the marker so this test can re-apply the patch after other test orderings.
    if hasattr(module, "_NIJA_HEARTBEAT_SINGLE_SOURCE_PATCHED"):
        delattr(module, "_NIJA_HEARTBEAT_SINGLE_SOURCE_PATCHED")
    _patch_runtime_authority_convergence(module)

    ok, detail = module._heartbeat_ready()
    assert ok is False
    assert detail == "heartbeat_uninitialized"
