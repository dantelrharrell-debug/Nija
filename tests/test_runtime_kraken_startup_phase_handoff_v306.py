from __future__ import annotations

import importlib
import threading
import time


MODULE = "bot.runtime_kraken_startup_phase_handoff_v306_patch"


class DummyBroker:
    broker_type = "kraken"
    account_identifier = "PLATFORM"


def _fresh_snapshot(broker: DummyBroker) -> None:
    now = time.monotonic()
    broker._nija_authoritative_position_snapshot_fetch_ok_v285 = True
    broker._nija_authoritative_position_snapshot_generation_v285 = 7
    broker._nija_authoritative_position_snapshot_at_monotonic_v285 = now
    broker._nija_authoritative_position_raw_generation_v286 = 7
    broker._nija_authoritative_position_raw_rows_v286 = (
        {"symbol": "ETH-USD", "quantity": 0.1, "authoritative_balance": True},
    )


def test_current_authoritative_rows_requires_original_ttl(monkeypatch):
    module = importlib.import_module(MODULE)
    broker = DummyBroker()
    _fresh_snapshot(broker)
    monkeypatch.setattr(module, "_snapshot_max_age_s", lambda: 90.0)

    ok, rows, age, maximum, reason = module._current_authoritative_rows(broker)
    assert ok is True
    assert rows == [{"symbol": "ETH-USD", "quantity": 0.1, "authoritative_balance": True}]
    assert age < maximum == 90.0
    assert reason == "current_balance_snapshot"

    broker._nija_authoritative_position_snapshot_at_monotonic_v285 = time.monotonic() - 91.0
    ok, rows, age, maximum, reason = module._current_authoritative_rows(broker)
    assert ok is False
    assert rows == []
    assert age >= maximum
    assert reason == "snapshot_stale"


def test_wrapper_reuses_only_current_authenticated_rows(monkeypatch):
    module = importlib.import_module(MODULE)
    broker = DummyBroker()
    _fresh_snapshot(broker)
    monkeypatch.setattr(
        module,
        "_bulk_flight_state",
        lambda _broker: {"active": True, "expired": False, "age_s": 12.0, "symbols": ("ETH-USD",)},
    )
    monkeypatch.setattr(module, "_should_log", lambda *_args, **_kwargs: False)

    calls = []

    def original(_broker):
        calls.append(True)
        return [{"symbol": "NEW"}]

    wrapped = module._wrap_authoritative_positions(original)
    result = wrapped(broker)
    assert result == [{"symbol": "ETH-USD", "quantity": 0.1, "authoritative_balance": True}]
    assert calls == []

    result[0]["quantity"] = 99
    assert broker._nija_authoritative_position_raw_rows_v286[0]["quantity"] == 0.1


def test_wrapper_fails_closed_when_history_active_and_snapshot_stale(monkeypatch):
    module = importlib.import_module(MODULE)
    broker = DummyBroker()
    _fresh_snapshot(broker)
    broker._nija_authoritative_position_snapshot_at_monotonic_v285 = time.monotonic() - 91.0
    monkeypatch.setattr(
        module,
        "_bulk_flight_state",
        lambda _broker: {"active": True, "expired": False, "age_s": 20.0, "symbols": ("ETH-USD",)},
    )
    monkeypatch.setattr(module, "_snapshot_max_age_s", lambda: 90.0)
    monkeypatch.setattr(module, "_should_log", lambda *_args, **_kwargs: False)

    calls = []

    def original(_broker):
        calls.append(True)
        return []

    wrapped = module._wrap_authoritative_positions(original)
    try:
        wrapped(broker)
    except TimeoutError as exc:
        assert "redundant Balance deferred" in str(exc)
    else:
        raise AssertionError("expected fail-closed TimeoutError")
    assert calls == []


def test_expired_phase_deferral_resumes_normal_balance(monkeypatch):
    module = importlib.import_module(MODULE)
    broker = DummyBroker()
    monkeypatch.setattr(
        module,
        "_bulk_flight_state",
        lambda _broker: {"active": False, "expired": True, "age_s": 361.0, "symbols": ("ETH-USD",)},
    )
    monkeypatch.setattr(module, "_should_log", lambda *_args, **_kwargs: False)

    calls = []

    def original(_broker):
        calls.append(True)
        return [{"symbol": "LIVE"}]

    wrapped = module._wrap_authoritative_positions(original)
    assert wrapped(broker) == [{"symbol": "LIVE"}]
    assert calls == [True]


def test_v305_chains_v306():
    source = importlib.import_module("bot.runtime_kraken_authoritative_snapshot_ownership_v305_patch")
    assert callable(getattr(source, "_install_v306_phase_handoff", None))
    assert "v306_phase_handoff" in source.install.__code__.co_consts
