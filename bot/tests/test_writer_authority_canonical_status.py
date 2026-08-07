from __future__ import annotations

import sys
from types import ModuleType

import pytest

from bot.heartbeat_state import get_heartbeat_state, reset_heartbeat_state_for_testing
from bot.writer_authority import WriterAuthority


def _install_distributed_status_stub(monkeypatch, *, strict_required: bool, ok: bool) -> None:
    module = ModuleType("bot.execution_authority_context")
    module.get_distributed_writer_authority_status = lambda force_refresh=False: {
        "effective_strict_required": strict_required,
        "ok": ok,
        "redis_reachable": ok,
    }
    monkeypatch.setitem(sys.modules, "bot.execution_authority_context", module)
    monkeypatch.delitem(sys.modules, "execution_authority_context", raising=False)


def _install_entrypoint_authority_stub(
    monkeypatch,
    *,
    acquired: bool,
    lost: bool,
    core_thread=None,
    instance_id: str = "",
) -> None:
    class _Authority:
        pass

    authority = _Authority()
    authority.acquired = acquired
    authority.lost = lost
    authority._core_thread = core_thread
    authority._instance_id = instance_id
    authority.result = None

    module = ModuleType("bot.entrypoint_writer_authority")
    module.get_entrypoint_writer_authority = lambda: authority
    monkeypatch.setitem(sys.modules, "bot.entrypoint_writer_authority", module)
    monkeypatch.delitem(sys.modules, "entrypoint_writer_authority", raising=False)


@pytest.fixture(autouse=True)
def _reset_heartbeat_state() -> None:
    reset_heartbeat_state_for_testing()


def test_get_status_ready_from_canonical_writer_signals(monkeypatch) -> None:
    _install_distributed_status_stub(monkeypatch, strict_required=False, ok=False)
    monkeypatch.setenv("NIJA_WRITER_STATE", "ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "9999999999")
    monkeypatch.setenv("NIJA_CORE_THREAD_ALIVE", "1")

    status = WriterAuthority.get_status(enforce_active_invariant=True)

    assert status.ready is True
    assert status.state == "ACTIVE"


def test_get_status_prefers_shared_heartbeat_state_when_env_timestamp_is_stale(monkeypatch) -> None:
    _install_distributed_status_stub(monkeypatch, strict_required=False, ok=False)
    monkeypatch.setenv("NIJA_WRITER_STATE", "ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "1")
    monkeypatch.setenv("NIJA_CORE_THREAD_ALIVE", "1")
    get_heartbeat_state().record_heartbeat(generation=9)

    status = WriterAuthority.get_status(enforce_active_invariant=True)

    assert status.ready is True
    assert status.checks["heartbeat_healthy"] is True


def test_active_state_invariant_raises_when_not_ready(monkeypatch, caplog) -> None:
    _install_distributed_status_stub(monkeypatch, strict_required=False, ok=False)
    monkeypatch.setenv("NIJA_WRITER_STATE", "ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "0")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "0")
    monkeypatch.setenv("NIJA_CORE_THREAD_ALIVE", "0")

    with caplog.at_level("CRITICAL", logger="nija.writer_authority"):
        with pytest.raises(RuntimeError, match="WRITER_STATE_INCONSISTENT"):
            WriterAuthority.get_status(enforce_active_invariant=True)

    assert "WRITER_STATE_INCONSISTENT" in caplog.text


def test_get_status_does_not_fail_local_authority_gate_when_singleton_unknown(monkeypatch) -> None:
    _install_distributed_status_stub(monkeypatch, strict_required=False, ok=False)
    _install_entrypoint_authority_stub(
        monkeypatch,
        acquired=False,
        lost=False,
        core_thread=None,
        instance_id="",
    )
    monkeypatch.setenv("NIJA_WRITER_STATE", "ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "9999999999")
    monkeypatch.delenv("NIJA_CORE_THREAD_ALIVE", raising=False)

    status = WriterAuthority.get_status(enforce_active_invariant=True)

    assert status.ready is True
    assert status.checks["local_authority_known_state"] is False


def test_get_status_startup_grace_when_core_thread_not_registered(monkeypatch) -> None:
    _install_distributed_status_stub(monkeypatch, strict_required=False, ok=False)
    _install_entrypoint_authority_stub(
        monkeypatch,
        acquired=True,
        lost=False,
        core_thread=None,
        instance_id="writer-1",
    )
    monkeypatch.setenv("NIJA_WRITER_STATE", "ACTIVE")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "9999999999")
    monkeypatch.delenv("NIJA_CORE_THREAD_ALIVE", raising=False)

    status = WriterAuthority.get_status(enforce_active_invariant=True)

    assert status.ready is True
    assert status.checks["core_thread_alive"] is True
