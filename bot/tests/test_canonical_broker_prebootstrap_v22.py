from __future__ import annotations

import types
from functools import wraps

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


def test_prepare_initializes_canonical_manager_before_self_healing(monkeypatch):
    manager = _ReadyManager()
    monkeypatch.setattr(guard, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(guard, "_READY", False)

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

    try:
        guard._initialize_manager(manager)
    except RuntimeError as exc:
        assert "without initializing the capital FSM" in str(exc)
    else:
        raise AssertionError("unrepaired capital FSM must remain fail-closed")


def test_initialize_does_not_retry_real_broker_failure():
    calls = []

    class Manager(_ReadyManager):
        def initialize(self):
            calls.append("initialize")
            raise RuntimeError("no exchange balance")

    manager = Manager()

    try:
        guard._initialize_manager(manager)
    except RuntimeError as exc:
        assert "no exchange balance" in str(exc)
    else:
        raise AssertionError("real broker failure must remain fail-closed")

    assert calls == ["initialize"]


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
