from __future__ import annotations

from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

import bot.runtime_heartbeat_broker_manager_terminal_v244_patch as patch


def test_verified_reason_uses_live_v233_grant_when_canonical_scope_unwound(monkeypatch):
    fake_v236 = SimpleNamespace(
        _verified_reason=lambda: ("HEARTBEAT_TRADE", "v233_grant"),
        _canonical_verified_probe=lambda: None,
    )
    monkeypatch.setattr(patch, "_v236", lambda: fake_v236)

    assert patch._verified_reason() == "HEARTBEAT_TRADE"


def test_verified_reason_remains_fail_closed_without_upstream_proof(monkeypatch):
    fake_v236 = SimpleNamespace(
        _verified_reason=lambda: (None, "none"),
        _canonical_verified_probe=lambda: None,
    )
    monkeypatch.setattr(patch, "_v236", lambda: fake_v236)

    assert patch._verified_reason() is None


def test_verified_heartbeat_is_reanchored_at_broker_manager(monkeypatch):
    module = ModuleType("bot.broker_manager")
    state = {"scope": False, "bindings": False, "calls": 0}

    @contextmanager
    def scope(reason):
        assert reason == "HEARTBEAT_TRADE"
        state["scope"] = True
        try:
            yield
        finally:
            state["scope"] = False

    @contextmanager
    def bindings(bound_module):
        assert bound_module is module
        state["bindings"] = True
        try:
            yield
        finally:
            state["bindings"] = False

    fake_v236 = SimpleNamespace(
        _authority_module=lambda: SimpleNamespace(startup_execution_probe_scope=scope),
        _canonical_terminal_bindings=bindings,
    )
    monkeypatch.setattr(patch, "_v236", lambda: fake_v236)
    monkeypatch.setattr(patch, "_verified_reason", lambda: "HEARTBEAT_TRADE")
    monkeypatch.setattr(patch, "_writer_ready", lambda: True)

    def submit(_self, value):
        state["calls"] += 1
        assert state["scope"] is True
        assert state["bindings"] is True
        return value

    wrapped = patch._wrap_method(submit, module, "CoinbaseBroker.place_market_order")
    assert wrapped(object(), "exchange-result") == "exchange-result"
    assert state["calls"] == 1
    assert state["scope"] is False
    assert state["bindings"] is False


def test_ordinary_boot_order_remains_blocked(monkeypatch):
    module = ModuleType("bot.broker_manager")
    monkeypatch.setattr(patch, "_verified_reason", lambda: None)
    monkeypatch.setattr(
        patch,
        "_writer_ready",
        lambda: pytest.fail("ordinary order must not reverify startup writer"),
    )

    def blocked(_self):
        raise RuntimeError("broker order submission blocked (reason=lifecycle_phase:BOOT)")

    wrapped = patch._wrap_method(blocked, module, "CoinbaseBroker.place_market_order")
    with pytest.raises(RuntimeError, match="lifecycle_phase:BOOT"):
        wrapped(object())


def test_verified_probe_without_current_writer_remains_fail_closed(monkeypatch):
    module = ModuleType("bot.broker_manager")
    monkeypatch.setattr(patch, "_verified_reason", lambda: "HEARTBEAT_TRADE")
    monkeypatch.setattr(patch, "_writer_ready", lambda: False)
    fake_v236 = SimpleNamespace(
        _authority_module=lambda: SimpleNamespace(startup_execution_probe_scope=lambda _reason: None),
        _canonical_terminal_bindings=lambda _module: None,
    )
    monkeypatch.setattr(patch, "_v236", lambda: fake_v236)

    def blocked(_self):
        raise RuntimeError("broker order submission blocked (reason=lifecycle_phase:BOOT)")

    wrapped = patch._wrap_method(blocked, module, "CoinbaseBroker.place_market_order")
    with pytest.raises(RuntimeError, match="lifecycle_phase:BOOT"):
        wrapped(object())
