from __future__ import annotations

import sys
from types import ModuleType

import pytest

from bot import runtime_heartbeat_terminal_authority_v276_patch as v276


class FakeExecutionBlocked(RuntimeError):
    pass


def _authority() -> ModuleType:
    module = ModuleType("bot.execution_authority_context")
    module.ExecutionBlocked = FakeExecutionBlocked
    return module


def test_trusted_startup_probe_crosses_only_lifecycle_denial(monkeypatch):
    authority = _authority()
    calls = {"ordinary": 0, "verify": 0}

    def current():
        calls["ordinary"] += 1
        raise FakeExecutionBlocked("lifecycle_phase:BOOT")

    def verified():
        calls["verify"] += 1
        return True, "HEARTBEAT_TRADE"

    monkeypatch.setattr(v276, "_verified_startup_probe", verified)
    wrapped = v276._wrap_assertion(current, authority)

    assert wrapped() is None
    assert calls == {"ordinary": 1, "verify": 1}


def test_ordinary_lifecycle_denial_remains_fail_closed(monkeypatch):
    authority = _authority()

    def current():
        raise FakeExecutionBlocked("lifecycle_phase:BOOT")

    monkeypatch.setattr(
        v276,
        "_verified_startup_probe",
        lambda: (False, "startup_probe_denied:probe_reason_not_whitelisted"),
    )
    wrapped = v276._wrap_assertion(current, authority)

    with pytest.raises(FakeExecutionBlocked, match="lifecycle_phase:BOOT"):
        wrapped()


def test_non_lifecycle_execution_denial_is_never_reconsidered(monkeypatch):
    authority = _authority()
    verification_called = {"value": False}

    def current():
        raise FakeExecutionBlocked("nonce.authority")

    def verified():
        verification_called["value"] = True
        return True, "HEARTBEAT_TRADE"

    monkeypatch.setattr(v276, "_verified_startup_probe", verified)
    wrapped = v276._wrap_assertion(current, authority)

    with pytest.raises(FakeExecutionBlocked, match="nonce.authority"):
        wrapped()
    assert verification_called["value"] is False


def test_unrelated_exception_is_never_swallowed(monkeypatch):
    authority = _authority()

    def current():
        raise RuntimeError("unexpected-terminal-error")

    monkeypatch.setattr(v276, "_verified_startup_probe", lambda: (True, "HEARTBEAT_TRADE"))
    wrapped = v276._wrap_assertion(current, authority)

    with pytest.raises(RuntimeError, match="unexpected-terminal-error"):
        wrapped()


def test_lifecycle_reason_match_is_exact():
    authority = _authority()
    assert v276._is_lifecycle_execution_block(authority, FakeExecutionBlocked("lifecycle_phase:BOOT"))
    assert v276._is_lifecycle_execution_block(authority, FakeExecutionBlocked("lifecycle_phase:WARM"))
    assert not v276._is_lifecycle_execution_block(authority, FakeExecutionBlocked("lifecycle_phase:LIVE"))
    assert not v276._is_lifecycle_execution_block(authority, FakeExecutionBlocked("state.live_active"))
