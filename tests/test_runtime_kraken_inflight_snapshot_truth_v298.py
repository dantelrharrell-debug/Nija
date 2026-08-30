from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import bot.runtime_kraken_inflight_snapshot_truth_v298_patch as v298


_PENDING = (
    "Kraken authoritative position Balance pending after 5.0s "
    "age=37.2s single_flight_reused=true"
)


def test_local_pending_timeout_matches_only_v286_bounded_wait():
    assert v298._local_pending_timeout(TimeoutError(_PENDING)) is True
    assert v298._local_pending_timeout(TimeoutError("socket timed out")) is False
    assert v298._local_pending_timeout(RuntimeError(_PENDING)) is False


def test_should_preserve_requires_current_preexisting_proof_and_active_flight(monkeypatch):
    broker = object()
    monkeypatch.setattr(v298, "_snapshot_age_s", lambda _broker: (22.0, 90.0))
    monkeypatch.setattr(v298, "_active_authoritative_flight", lambda _broker: (True, 31.0))

    preserve, reason, age, max_age, flight_age = v298._should_preserve(
        broker,
        TimeoutError(_PENDING),
        pre_ready=True,
    )

    assert preserve is True
    assert reason == "current_proof_refresh_still_inflight"
    assert age == 22.0
    assert max_age == 90.0
    assert flight_age == 31.0


def test_should_preserve_fails_closed_after_original_snapshot_expiry(monkeypatch):
    broker = object()
    monkeypatch.setattr(v298, "_snapshot_age_s", lambda _broker: (90.0, 90.0))
    monkeypatch.setattr(v298, "_active_authoritative_flight", lambda _broker: (True, 31.0))

    preserve, reason, *_ = v298._should_preserve(
        broker,
        TimeoutError(_PENDING),
        pre_ready=True,
    )

    assert preserve is False
    assert reason == "snapshot_not_current"


def test_should_preserve_rejects_completed_or_missing_flight(monkeypatch):
    broker = object()
    monkeypatch.setattr(v298, "_snapshot_age_s", lambda _broker: (20.0, 90.0))
    monkeypatch.setattr(v298, "_active_authoritative_flight", lambda _broker: (False, 40.0))

    preserve, reason, *_ = v298._should_preserve(
        broker,
        TimeoutError(_PENDING),
        pre_ready=True,
    )
    assert preserve is False
    assert reason == "authoritative_flight_not_active"

    preserve, reason, *_ = v298._should_preserve(
        broker,
        RuntimeError("EGeneral:Internal error"),
        pre_ready=True,
    )
    assert preserve is False
    assert reason == "not_local_pending_timeout"

    preserve, reason, *_ = v298._should_preserve(
        broker,
        TimeoutError(_PENDING),
        pre_ready=False,
    )
    assert preserve is False
    assert reason == "preexisting_proof_not_ready"


def test_snapshot_age_uses_v285_monotonic_clock_without_extending_ttl(monkeypatch):
    broker = SimpleNamespace(
        _nija_authoritative_position_snapshot_at_monotonic_v285=time.monotonic() - 12.0
    )
    fake_v285 = SimpleNamespace(_snapshot_max_age_s=lambda: 90.0)
    monkeypatch.setattr(v298, "_v285", lambda: fake_v285)

    age, max_age = v298._snapshot_age_s(broker)

    assert 11.0 <= age <= 13.0
    assert max_age == 90.0


def test_active_authoritative_flight_requires_same_unfinished_v286_flight(monkeypatch):
    broker = object()
    event = threading.Event()
    lock = threading.RLock()
    fake_v286 = SimpleNamespace(
        _AUTH_LOCK=lock,
        _AUTH_FLIGHTS={
            id(broker): {
                "event": event,
                "error": None,
                "started_at": time.monotonic() - 8.0,
            }
        },
    )
    monkeypatch.setattr(v298, "_v286", lambda: fake_v286)

    active, age = v298._active_authoritative_flight(broker)
    assert active is True
    assert 7.0 <= age <= 9.0

    event.set()
    active, _age = v298._active_authoritative_flight(broker)
    assert active is False


def test_restore_proof_fields_does_not_touch_snapshot_timestamp_or_generation():
    broker = SimpleNamespace(
        _startup_position_sync_adopted=True,
        _startup_position_sync_symbols=("ETH-USD",),
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_error=None,
        _nija_authoritative_position_snapshot_fetch_ok_v285=True,
        _nija_authoritative_position_snapshot_error_v285="",
        _nija_authoritative_position_snapshot_at_monotonic_v285=123.5,
        _nija_authoritative_position_snapshot_generation_v285=17,
    )
    prior = v298._capture_proof_fields(broker)

    broker._startup_position_sync_adopted = False
    broker._startup_position_sync_symbols = ()
    broker._startup_position_sync_fetch_ok = False
    broker._startup_position_sync_error = "TimeoutError:pending"
    broker._nija_authoritative_position_snapshot_fetch_ok_v285 = False
    broker._nija_authoritative_position_snapshot_error_v285 = "TimeoutError:pending"

    v298._restore_proof_fields(broker, prior)

    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_symbols == ("ETH-USD",)
    assert broker._startup_position_sync_fetch_ok is True
    assert broker._startup_position_sync_error is None
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is True
    assert broker._nija_authoritative_position_snapshot_error_v285 == ""
    assert broker._nija_authoritative_position_snapshot_at_monotonic_v285 == 123.5
    assert broker._nija_authoritative_position_snapshot_generation_v285 == 17


def test_adopter_restores_only_preexisting_proof_on_exact_inflight_wait(monkeypatch):
    broker = SimpleNamespace(
        broker_type="kraken",
        account_identifier="PLATFORM",
        _startup_position_sync_adopted=True,
        _startup_position_sync_symbols=("ETH-USD",),
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_error=None,
        _nija_authoritative_position_snapshot_fetch_ok_v285=True,
        _nija_authoritative_position_snapshot_error_v285="",
    )

    def inner(real_broker, broker_name, eps):
        real_broker._startup_position_sync_adopted = False
        real_broker._startup_position_sync_symbols = ()
        real_broker._startup_position_sync_fetch_ok = False
        real_broker._startup_position_sync_error = "TimeoutError:pending"
        real_broker._nija_authoritative_position_snapshot_fetch_ok_v285 = False
        real_broker._nija_authoritative_position_snapshot_error_v285 = "TimeoutError:pending"
        raise TimeoutError(_PENDING)

    fake_sync = SimpleNamespace(_adopt_broker_positions=inner)
    original_import = v298.importlib.import_module

    def fake_import(name):
        if name == "bot.startup_position_sync":
            return fake_sync
        return original_import(name)

    monkeypatch.setattr(v298.importlib, "import_module", fake_import)
    monkeypatch.setattr(v298, "_strong_proof", lambda _broker: (True, "strong_current"))
    monkeypatch.setattr(
        v298,
        "_should_preserve",
        lambda _broker, _exc, pre_ready: (
            bool(pre_ready),
            "current_proof_refresh_still_inflight",
            20.0,
            90.0,
            30.0,
        ),
    )

    assert v298._patch_startup_adopter() is True
    assert fake_sync._adopt_broker_positions(broker, "platform:kraken", object()) == 0
    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_symbols == ("ETH-USD",)
    assert broker._startup_position_sync_fetch_ok is True
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is True
