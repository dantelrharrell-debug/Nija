from __future__ import annotations

import builtins
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bot.activation_convergence_v17_patch import (
    install,
    install_import_hook,
)
from bot.entrypoint_writer_authority import (
    EntrypointWriterAuthority,
    EntrypointWriterAuthorityResult,
)
from bot.startup_coordinator import RuntimeAuthorityState, get_startup_coordinator


@pytest.fixture(autouse=True)
def _clean_runtime(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "NIJA_WRITER_LEASE_ACQUIRED",
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_LEASE_GENERATION",
        "NIJA_WRITER_GENERATION",
        "NIJA_WRITER_HEARTBEAT_ACTIVE",
        "NIJA_WRITER_LEASE_RENEWAL_ACTIVE",
        "NIJA_WRITER_LEASE_RENEWED_TS",
        "NIJA_REDIS_URL",
        "REDIS_URL",
        "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
    ):
        monkeypatch.delenv(name, raising=False)
    coordinator = get_startup_coordinator()
    coordinator.reset_for_testing()
    yield
    coordinator.reset_for_testing()


def test_startup_coordinator_treats_capital_ready_as_running_equivalent() -> None:
    """CapitalBootstrapFSM READY must not strand LIVE activation at commit_version=0."""
    coordinator = get_startup_coordinator()
    coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
    coordinator.record_capital_state(
        state="READY",
        hydrated=True,
        balance=395.30,
        stale=False,
    )
    coordinator.record_threads_supervised(2, bootstrap_state="RUNNING_SUPERVISED")
    coordinator.record_authority(ready=True, status={"ok": True})
    coordinator.record_nonce_status(ready=True, detail="nonce_ready")
    coordinator.record_dispatch_health(ready=True, detail="dispatch_ready")
    coordinator.record_activation_requested(requested=True, source="unit-test")

    snapshot = coordinator.build_snapshot(
        trading_state="LIVE_PENDING_CONFIRMATION",
        activation_intent=True,
    )
    proof = coordinator.evaluate_system_readiness_proof(snapshot)

    assert snapshot.capital_state == "READY"
    assert snapshot.runtime_authority_state == RuntimeAuthorityState.AUTHORIZED.value
    assert proof.passed is True
    assert proof.first_blocking_gate == "none"


def _seed_acquired_runtime(*, thread_alive: bool, renewal_age_s: float) -> EntrypointWriterAuthority:
    runtime = EntrypointWriterAuthority()
    runtime._result = EntrypointWriterAuthorityResult(
        acquired=True,
        token="101",
        generation=77,
        instance_id="test",
        lock_key="nija:test",
    )
    runtime._generation = 77
    runtime._ttl_s = 60
    runtime._local_fallback = False
    runtime._lost.clear()
    runtime._stop.clear()
    runtime._heartbeat_thread = SimpleNamespace(is_alive=lambda: thread_alive)
    runtime._nija_last_lease_renewal_monotonic = time.monotonic() - renewal_age_s
    return runtime


def test_lease_renewal_health_rejects_dead_thread() -> None:
    runtime = _seed_acquired_runtime(thread_alive=False, renewal_age_s=1.0)
    ok, reason, _age_s, _max_age_s = runtime._nija_lease_renewal_health()
    assert ok is False
    assert reason == "renewal_thread_not_alive"


def test_lease_renewal_health_rejects_stale_success() -> None:
    runtime = _seed_acquired_runtime(thread_alive=True, renewal_age_s=100.0)
    ok, reason, age_s, max_age_s = runtime._nija_lease_renewal_health()
    assert ok is False
    assert reason == "renewal_success_stale"
    assert age_s > max_age_s


def test_retired_shim_is_side_effect_free() -> None:
    original_import = builtins.__import__

    assert install_import_hook() is True
    assert install() is True
    assert builtins.__import__ is original_import


def test_reentry_proof_uses_exact_redis_metadata_not_legacy_alive_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.writer_authority_recursion_guard_patch as guard

    now = time.time()
    client = MagicMock()
    client.get.return_value = json.dumps(
        {
            "token": "token-123",
            "generation": 3323,
            "heartbeat_at": now,
        }
    )
    runtime = SimpleNamespace(client=client, _client=client, _meta_key="writer:meta", _ttl_s=60)
    monkeypatch.setattr(
        guard,
        "_exact_process_writer_proof",
        lambda: (
            {
                "runtime": runtime,
                "client": client,
                "token": "token-123",
                "generation": 3323,
            },
            "",
        ),
    )
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "3323")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "1")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")

    proof = guard._writer_reentry_proof()

    assert proof["ok"] is True
    assert proof["reason"] == "exact_redis_writer_metadata"
    assert proof["heartbeat_age_s"] < 1.0
    assert os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] == "1"
