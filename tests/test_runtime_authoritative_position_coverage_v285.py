from types import SimpleNamespace

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
