from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest


class Broker:
    def __init__(self, connected):
        self.connected = connected


class BrokerProxy:
    def __init__(self, broker, connected=None):
        self._broker = broker
        if connected is not None:
            self.connected = connected


def test_exact_broker_health_requires_positive_local_state():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    ok, reason = v339._exact_broker_health(Broker(True))
    assert ok is True
    assert reason == "broker_local:connected"

    ok, reason = v339._exact_broker_health(Broker(False))
    assert ok is False
    assert reason == "broker_local:connected=false"


def test_exact_broker_health_uses_concrete_broker_behind_known_proxy():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")

    # A stale proxy false must not veto a healthy concrete adapter.
    ok, reason = v339._exact_broker_health(BrokerProxy(Broker(True), connected=False))
    assert ok is True
    assert reason == "broker_proxy:_broker->broker_local:connected"

    # A stale proxy true must not promote an unhealthy concrete adapter.
    ok, reason = v339._exact_broker_health(BrokerProxy(Broker(False), connected=True))
    assert ok is False
    assert reason == "broker_proxy:_broker->broker_local:connected=false"


def test_exact_broker_health_fails_closed_on_proxy_cycle():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    left = BrokerProxy(None)
    right = BrokerProxy(left)
    left._broker = right

    ok, reason = v339._exact_broker_health(left)
    assert ok is False
    assert reason == "broker_proxy_cycle"


def test_exact_broker_health_fails_closed_without_state():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    ok, reason = v339._exact_broker_health(object())
    assert ok is False
    assert reason == "exact_broker_health_unproven"


def test_trusted_kwargs_reuses_v335_full_contract():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    assert v339._trusted_kwargs({
        "intent_type": "exit",
        "position_effect": "close",
        "metadata_override": {
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
        },
    }) is True
    assert v339._trusted_kwargs({
        "intent_type": "entry",
        "position_effect": "close",
        "metadata_override": {
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
        },
    }) is False


def test_exact_broker_reproof_denies_active_kill_switch_even_for_trusted_close(monkeypatch):
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")

    snap = SimpleNamespace(
        kill_switch_active=True,
        nonce_ready=True,
        ready=False,
        lifecycle_phase="BOOT",
        reason="startup activation convergence",
        coordinator_state="ACTIVATION_CONVERGING",
        dispatch_health_ready=False,
    )
    eac = SimpleNamespace(
        runtime_authority_snapshot=lambda: snap,
        assert_distributed_writer_authority=lambda: None,
        require_startup_execution_authority=lambda **kwargs: None,
        is_seak_halted=lambda: False,
    )
    v337 = SimpleNamespace(_trusted_close=lambda: True)
    monkeypatch.setitem(sys.modules, "bot.execution_authority_context", eac)
    monkeypatch.setitem(sys.modules, "bot.runtime_protective_exit_authority_bridge_v337_patch", v337)
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "test-fencing-token")
    monkeypatch.setenv("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED")

    token = v339._BROKER.set(Broker(True))
    try:
        ok, reason, returned = v339._reprove_without_global_health()
    finally:
        v339._BROKER.reset(token)

    assert ok is False
    assert reason == "kill_switch_active"
    assert returned is snap

    v337._trusted_close = lambda: False
    token = v339._BROKER.set(Broker(True))
    try:
        ok, reason, returned = v339._reprove_without_global_health()
    finally:
        v339._BROKER.reset(token)

    assert ok is False
    assert reason == "kill_switch_active"
    assert returned is snap

@pytest.mark.parametrize("state", [None, "false", 0])
def test_exact_broker_reproof_requires_explicit_clear_stop_state(monkeypatch, state):
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    snap = SimpleNamespace() if state is None else SimpleNamespace(kill_switch_active=state)
    monkeypatch.setitem(sys.modules, "bot.execution_authority_context", SimpleNamespace(
        runtime_authority_snapshot=lambda: snap,
        assert_distributed_writer_authority=lambda: None,
        require_startup_execution_authority=lambda **kwargs: None,
    ))
    token = v339._BROKER.set(Broker(True))
    try:
        ok, reason, returned = v339._reprove_without_global_health()
    finally:
        v339._BROKER.reset(token)
    assert ok is False
    assert reason == "kill_switch_state_unproven"
    assert returned is snap


@pytest.mark.parametrize("missing_gate,expected", [
    ("writer", "writer_authority:"),
    ("startup", "writer_authority:"),
    ("nonce", "nonce_not_ready"),
    ("seak", "seak_halted"),
    ("circuit", "execution_circuit:OPEN"),
    ("fencing", "writer_fencing_token_missing"),
    ("broker", "exact_broker:broker_local:connected=false"),
])
def test_exact_broker_reproof_preserves_hard_safety_denials(monkeypatch, missing_gate, expected):
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    snap = SimpleNamespace(
        kill_switch_active=False, nonce_ready=missing_gate != "nonce", ready=False,
        lifecycle_phase="BOOT", reason="startup", coordinator_state="ACTIVATION_CONVERGING",
    )

    def writer():
        if missing_gate == "writer":
            raise RuntimeError("writer lost")

    def startup(**kwargs):
        if missing_gate == "startup":
            raise RuntimeError("startup authority missing")

    monkeypatch.setitem(sys.modules, "bot.execution_authority_context", SimpleNamespace(
        runtime_authority_snapshot=lambda: snap,
        assert_distributed_writer_authority=writer,
        require_startup_execution_authority=startup,
        is_seak_halted=lambda: missing_gate == "seak",
    ))
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "" if missing_gate == "fencing" else "test-token")
    monkeypatch.setenv("NIJA_EXECUTION_CIRCUIT_STATE", "OPEN" if missing_gate == "circuit" else "CLOSED")
    token = v339._BROKER.set(Broker(missing_gate != "broker"))
    try:
        ok, reason, _ = v339._reprove_without_global_health()
    finally:
        v339._BROKER.reset(token)
    assert ok is False
    assert reason.startswith(expected)
