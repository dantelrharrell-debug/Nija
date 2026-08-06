from __future__ import annotations

import sys
from types import ModuleType

import pytest

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
