import sys
import threading
from types import ModuleType, SimpleNamespace

from bot import runtime_authoritative_position_coverage_v285_patch as v285


def broker(*, connected=True, fetch_ok=True, adopted=True, symbols=("BTC-USD",)):
    return SimpleNamespace(
        connected=connected,
        _startup_position_sync_fetch_ok=fetch_ok,
        _startup_position_sync_adopted=adopted,
        _startup_position_sync_symbols=tuple(symbols),
        _startup_position_sync_error="",
    )


def test_snapshot_rows_capture_authoritative_quantity_entry_and_cost_basis():
    rows, error = v285._snapshot_rows([
        {
            "symbol": "BTC/USD",
            "quantity": 0.25,
            "entry_price": 40000.0,
            "cost_basis": 10000.0,
        }
    ])
    assert error == ""
    assert rows == (
        {
            "symbol": "BTC-USD",
            "quantity": 0.25,
            "entry_price": 40000.0,
            "cost_basis": 10000.0,
        },
    )


def test_invalid_snapshot_payload_fails_closed():
    rows, error = v285._snapshot_rows([{"symbol": "BTC-USD", "quantity": 0.0}])
    assert rows == ()
    assert error.startswith("invalid_position_row:")


def test_strong_proof_requires_independent_fetch_proof():
    b = broker(fetch_ok=False, adopted=True)
    v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )
    ready, reason = v285._strong_broker_proof(b)
    assert ready is False
    assert reason == "authoritative_position_fetch_unproven"


def test_strong_proof_requires_adoption():
    b = broker(fetch_ok=True, adopted=False)
    v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )
    ready, reason = v285._strong_broker_proof(b)
    assert ready is False
    assert reason == "position_snapshot_not_adopted"


def test_current_authoritative_snapshot_is_accepted(monkeypatch):
    clock = {"value": 1000.0}
    monkeypatch.setattr(v285.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90")

    b = broker()
    assert v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )

    clock["value"] = 1040.0
    ready, reason = v285._strong_broker_proof(b)
    assert ready is True
    assert reason == "authoritative_current_position_snapshot_adopted"


def test_stale_authoritative_snapshot_fails_closed(monkeypatch):
    clock = {"value": 1000.0}
    monkeypatch.setattr(v285.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "30")

    b = broker()
    assert v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )

    clock["value"] = 1031.0
    ready, reason = v285._strong_broker_proof(b)
    assert ready is False
    assert reason.startswith("stale_position_snapshot:")


def test_disconnected_account_never_qualifies_even_with_prior_snapshot():
    b = broker(connected=True)
    v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )
    b.connected = False
    ready, reason = v285._strong_broker_proof(b)
    assert ready is False
    assert reason == "disconnected"


def test_v399_active_kraken_refresh_preserves_current_prior_proof(monkeypatch):
    clock = {"value": 1000.0}
    monkeypatch.setattr(v285.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90")

    b = broker(fetch_ok=True, adopted=True)
    b.broker_type = "kraken"
    assert v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )

    # Simulate legacy flags clearing while the exact authenticated v286 flight
    # is still active.  Prior-good proof and the original snapshot remain real.
    b._startup_position_sync_fetch_ok = None
    b._startup_position_sync_adopted = False
    b._startup_position_sync_error = "Kraken authoritative position Balance pending after 5.0s"

    event = threading.Event()
    fake_v286 = ModuleType("bot.runtime_kraken_position_refresh_liveness_v286_patch")
    fake_v286._LAST_PROOF_READY = {id(b): True}
    fake_v286._AUTH_FLIGHTS = {
        id(b): {"event": event, "error": None, "started_at": 1001.0}
    }
    fake_v286._AUTH_LOCK = threading.RLock()
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_kraken_position_refresh_liveness_v286_patch",
        fake_v286,
    )

    clock["value"] = 1040.0
    ready, reason = v285._strong_broker_proof(b)
    assert ready is True
    assert reason == "authoritative_current_position_snapshot_refresh_inflight_v399"


def test_v399_completed_kraken_refresh_fails_closed(monkeypatch):
    clock = {"value": 1000.0}
    monkeypatch.setattr(v285.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90")

    b = broker(fetch_ok=True, adopted=True)
    b.broker_type = "kraken"
    assert v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )
    b._startup_position_sync_fetch_ok = False
    b._startup_position_sync_adopted = False
    b._startup_position_sync_error = "completed_exchange_failure"

    event = threading.Event()
    event.set()
    fake_v286 = ModuleType("bot.runtime_kraken_position_refresh_liveness_v286_patch")
    fake_v286._LAST_PROOF_READY = {id(b): True}
    fake_v286._AUTH_FLIGHTS = {
        id(b): {"event": event, "error": None, "started_at": 1001.0}
    }
    fake_v286._AUTH_LOCK = threading.RLock()
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_kraken_position_refresh_liveness_v286_patch",
        fake_v286,
    )

    ready, reason = v285._strong_broker_proof(b)
    assert ready is False
    assert reason == "completed_exchange_failure"


def test_v399_stale_snapshot_still_fails_closed_during_active_refresh(monkeypatch):
    clock = {"value": 1000.0}
    monkeypatch.setattr(v285.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "30")

    b = broker(fetch_ok=True, adopted=True)
    b.broker_type = "kraken"
    assert v285._record_snapshot_success(
        b,
        [{"symbol": "BTC-USD", "quantity": 0.01, "entry_price": 50000.0}],
    )
    b._startup_position_sync_fetch_ok = None
    b._startup_position_sync_adopted = False
    b._startup_position_sync_error = "refresh_pending"

    event = threading.Event()
    fake_v286 = ModuleType("bot.runtime_kraken_position_refresh_liveness_v286_patch")
    fake_v286._LAST_PROOF_READY = {id(b): True}
    fake_v286._AUTH_FLIGHTS = {
        id(b): {"event": event, "error": None, "started_at": 1001.0}
    }
    fake_v286._AUTH_LOCK = threading.RLock()
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_kraken_position_refresh_liveness_v286_patch",
        fake_v286,
    )

    clock["value"] = 1031.0
    ready, reason = v285._strong_broker_proof(b)
    assert ready is False
    assert reason == "refresh_pending"
