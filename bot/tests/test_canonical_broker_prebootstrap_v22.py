from __future__ import annotations

import os
import threading
import types
from functools import wraps

import pytest

import bot.canonical_broker_prebootstrap_v22 as guard


class _BrokerType:
    value = "kraken"


class _Broker:
    connected = True


class _ReadyManager:
    def __init__(self):
        self._fsm_initialized = True
        self._platform_brokers = {_BrokerType(): _Broker()}
        self.initialize_calls = 0

    def initialize(self):
        self.initialize_calls += 1

    def has_registered_sources(self):
        return True

    def has_attempted_connections(self):
        return True


def _set_writer_proof(monkeypatch):
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "fence-token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "3774")


def _set_live_mode(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "false")
    monkeypatch.setenv("LIVE_TRADING", "true")


def _ready_snapshot():
    return {
        "broker_connected": True,
        "balance_hydrated": True,
        "authority_ready": False,
        "capital_ready": True,
        "risk_ready": True,
        "strategy_ready": False,
        "execution_ready": False,
        "nonce_ready": False,
        "bootstrap_ready": False,
    }


def test_prepare_initializes_canonical_manager_before_self_healing(monkeypatch):
    manager = _ReadyManager()
    monkeypatch.setattr(guard, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(guard, "_READY", False)
    monkeypatch.setattr(guard, "_is_live_mode", lambda: False)

    result = guard.prepare_canonical_broker_runtime()

    assert result is manager
    assert manager.initialize_calls == 1


def test_initialize_retries_only_missing_fsm_latch():
    calls = []

    class Manager(_ReadyManager):
        def __init__(self):
            super().__init__()
            self._fsm_initialized = False

        def initialize(self):
            calls.append("initialize")
            if len(calls) == 1:
                raise RuntimeError("stale init registry latch")

        def _init_capital_fsm(self):
            calls.append("repair")
            self._fsm_initialized = True

    manager = Manager()
    guard._initialize_manager(manager)

    assert calls == ["initialize", "repair", "initialize"]
    assert manager._fsm_initialized is True


def test_initialize_repairs_silent_missing_fsm_latch():
    calls = []

    class Manager(_ReadyManager):
        def __init__(self):
            super().__init__()
            self._fsm_initialized = False

        def initialize(self):
            calls.append("initialize")

        def _init_capital_fsm(self):
            calls.append("repair")
            self._fsm_initialized = True

    manager = Manager()
    guard._initialize_manager(manager)

    assert calls == ["initialize", "repair"]
    assert manager._fsm_initialized is True


def test_initialize_fails_closed_when_silent_latch_cannot_be_repaired():
    class Manager(_ReadyManager):
        def __init__(self):
            super().__init__()
            self._fsm_initialized = False

        def initialize(self):
            return None

        def _init_capital_fsm(self):
            return None

    manager = Manager()

    with pytest.raises(RuntimeError, match="without initializing the capital FSM"):
        guard._initialize_manager(manager)


def test_initialize_does_not_retry_real_broker_failure():
    calls = []

    class Manager(_ReadyManager):
        def initialize(self):
            calls.append("initialize")
            raise RuntimeError("no exchange balance")

    manager = Manager()

    with pytest.raises(RuntimeError, match="no exchange balance"):
        guard._initialize_manager(manager)

    assert calls == ["initialize"]


def test_live_initialization_hands_off_after_strict_current_proof(monkeypatch):
    release = threading.Event()

    class Manager(_ReadyManager):
        def initialize(self):
            self.initialize_calls += 1
            release.wait(timeout=5)

    manager = Manager()
    _set_writer_proof(monkeypatch)
    monkeypatch.setattr(
        guard,
        "_readiness_handoff_proof",
        lambda: (True, "readiness_ready", _ready_snapshot()),
    )

    try:
        assert guard._live_initialize_with_handoff(manager) is True
        assert manager.initialize_calls == 1
    finally:
        release.set()


def test_missing_fencing_token_prevents_early_handoff(monkeypatch):
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.delenv("NIJA_WRITER_FENCING_TOKEN", raising=False)
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "3774")

    ok, reason = guard._writer_handoff_proof()

    assert ok is False
    assert reason == "writer_fencing_token_missing"


def test_generation_zero_prevents_early_handoff(monkeypatch):
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "fence-token")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "0")

    ok, reason = guard._writer_handoff_proof()

    assert ok is False
    assert reason == "writer_generation_not_positive"


def test_missing_manager_contract_prevents_early_handoff(monkeypatch):
    manager = _ReadyManager()
    manager._fsm_initialized = False
    _set_writer_proof(monkeypatch)

    ok, reason, _ = guard._prebootstrap_handoff_proof(manager)

    assert ok is False
    assert reason == "fsm_not_initialized"


def test_no_connected_platform_broker_prevents_early_handoff(monkeypatch):
    manager = _ReadyManager()
    manager._platform_brokers = {_BrokerType(): types.SimpleNamespace(connected=False)}
    _set_writer_proof(monkeypatch)

    ok, reason, _ = guard._prebootstrap_handoff_proof(manager)

    assert ok is False
    assert reason == "no_connected_platform_broker"


@pytest.mark.parametrize(
    "false_key",
    ["broker_connected", "balance_hydrated", "capital_ready", "risk_ready"],
)
def test_any_required_readiness_false_prevents_early_handoff(monkeypatch, false_key):
    snapshot = _ready_snapshot()
    snapshot[false_key] = False
    monkeypatch.setattr(
        guard,
        "importlib",
        types.SimpleNamespace(
            import_module=lambda name: types.SimpleNamespace(snapshot=lambda: snapshot)
            if name == "bot.readiness_table"
            else __import__(name, fromlist=["*"])
        ),
    )

    ok, reason, returned = guard._readiness_handoff_proof()

    assert ok is False
    assert false_key in reason
    assert returned[false_key] is False


def test_live_initialization_exception_propagates_and_remains_fail_closed():
    class Manager(_ReadyManager):
        def initialize(self):
            raise RuntimeError("exchange authentication failed")

    manager = Manager()

    with pytest.raises(RuntimeError, match="exchange authentication failed"):
        guard._live_initialize_with_handoff(manager)


def test_live_handoff_timeout_fails_closed(monkeypatch):
    release = threading.Event()

    class Manager(_ReadyManager):
        def initialize(self):
            release.wait(timeout=5)

    manager = Manager()
    monkeypatch.setenv("NIJA_PREBOOTSTRAP_HANDOFF_TIMEOUT_S", "1")
    monkeypatch.setattr(guard, "_prebootstrap_handoff_proof", lambda manager: (False, "not_ready", {}))
    monotonic_values = iter([0.0, 2.0])
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(monotonic_values))

    try:
        with pytest.raises(RuntimeError, match="live handoff timed out"):
            guard._live_initialize_with_handoff(manager)
    finally:
        release.set()


def test_early_handoff_does_not_grant_execution_or_other_activation_readiness(monkeypatch):
    release = threading.Event()

    class Manager(_ReadyManager):
        def initialize(self):
            release.wait(timeout=5)

    manager = Manager()
    _set_live_mode(monkeypatch)
    _set_writer_proof(monkeypatch)
    snapshot = _ready_snapshot()
    monkeypatch.setattr(
        guard,
        "_readiness_handoff_proof",
        lambda: (True, "readiness_ready", dict(snapshot)),
    )
    guarded_env = (
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        "NIJA_LIVE_ACTIVE",
        "NIJA_EXECUTION_READY",
        "NIJA_NONCE_READY",
        "NIJA_STRATEGY_READY",
        "NIJA_BOOTSTRAP_READY",
    )
    for name in guarded_env:
        monkeypatch.delenv(name, raising=False)

    before = dict(snapshot)
    try:
        assert guard._live_initialize_with_handoff(manager) is True
        assert snapshot == before
        for name in guarded_env:
            assert os.getenv(name) is None
    finally:
        release.set()


def test_writer_wrapper_runs_prebootstrap_after_authority(monkeypatch):
    sequence = []
    module = types.SimpleNamespace(
        __name__="bot.bot_main",
        _acquire_writer_authority_before_nonce=lambda: sequence.append("authority") or True,
        _release_writer_authority=lambda: sequence.append("release"),
    )
    monkeypatch.setattr(
        guard,
        "prepare_canonical_broker_runtime",
        lambda: sequence.append("prebootstrap"),
    )

    assert guard._patch_writer_acquire(module)
    assert module._acquire_writer_authority_before_nonce() is True
    assert sequence == ["authority", "prebootstrap"]


def test_writer_wrapper_releases_own_lease_on_prebootstrap_failure(monkeypatch):
    sequence = []
    module = types.SimpleNamespace(
        __name__="bot.bot_main",
        _acquire_writer_authority_before_nonce=lambda: sequence.append("authority") or True,
        _release_writer_authority=lambda: sequence.append("release"),
    )

    def fail():
        sequence.append("prebootstrap")
        raise RuntimeError("manager unavailable")

    monkeypatch.setattr(guard, "prepare_canonical_broker_runtime", fail)

    assert guard._patch_writer_acquire(module)
    assert module._acquire_writer_authority_before_nonce() is False
    assert sequence == ["authority", "prebootstrap", "release"]


def test_writer_wrapper_preserves_existing_recovery_layer(monkeypatch):
    sequence = []

    def base():
        sequence.append("base")
        return True

    @wraps(base)
    def recovery_layer():
        sequence.append("recovery")
        return base()

    recovery_layer._nija_writer_reelection_v39 = True

    module = types.SimpleNamespace(
        __name__="bot.bot_main",
        _acquire_writer_authority_before_nonce=recovery_layer,
        _release_writer_authority=lambda: sequence.append("release"),
    )
    monkeypatch.setattr(
        guard,
        "prepare_canonical_broker_runtime",
        lambda: sequence.append("prebootstrap"),
    )

    assert guard._patch_writer_acquire(module)
    wrapped = module._acquire_writer_authority_before_nonce
    assert wrapped() is True
    assert sequence == ["recovery", "base", "prebootstrap"]
    assert getattr(wrapped.__wrapped__, "_nija_writer_reelection_v39", False) is True


def test_writer_wrapper_repatch_does_not_duplicate_or_unwrap_layers(monkeypatch):
    sequence = []

    def base():
        sequence.append("base")
        return True

    @wraps(base)
    def recovery_layer():
        sequence.append("recovery")
        return base()

    recovery_layer._nija_writer_reelection_v39 = True

    module = types.SimpleNamespace(
        __name__="bot.bot_main",
        _acquire_writer_authority_before_nonce=recovery_layer,
        _release_writer_authority=lambda: sequence.append("release"),
    )
    monkeypatch.setattr(
        guard,
        "prepare_canonical_broker_runtime",
        lambda: sequence.append("prebootstrap"),
    )

    assert guard._patch_writer_acquire(module)
    first = module._acquire_writer_authority_before_nonce
    assert guard._patch_writer_acquire(module)
    second = module._acquire_writer_authority_before_nonce

    assert second is first
    assert guard._wrapper_chain_has_marker(second, guard._ACQUIRE_WRAP_ATTR)
    assert second() is True
    assert sequence == ["recovery", "base", "prebootstrap"]
