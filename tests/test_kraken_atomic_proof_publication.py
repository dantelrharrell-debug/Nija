"""Concurrent Kraken Balance publication must be observed as one proof generation.

Only v286's authenticated Balance reader may issue Kraken raw-row provenance;
the v98/v315 consumer must not adopt half-published or stale generations.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import bot.position_sync_failure_truth_v98_patch as v98
import bot.runtime_authoritative_position_coverage_v285_patch as v285
import bot.runtime_kraken_position_refresh_liveness_v286_patch as v286


def _broker():
    return SimpleNamespace(connected=True, broker_type="kraken")


def _rows():
    return [{
        "symbol": "BTC-USD", "quantity": 0.25, "entry_price": 50000.0,
        "cost_basis": 12500.0, "authoritative_balance": True,
        "tradable": True, "pricing_verified": True, "raw_asset": "XXBT",
    }]


def test_kraken_reader_waits_for_complete_authenticated_publication(monkeypatch):
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    first_generation = broker._nija_authoritative_position_snapshot_generation_v285

    original = v285._record_snapshot_success
    canonical_published = threading.Event()
    allow_raw_certificate = threading.Event()
    reader_started = threading.Event()
    reader_done = threading.Event()
    errors = []
    results = []

    def pause_between_canonical_and_raw(target, returned):
        ready = original(target, returned)
        canonical_published.set()
        if not allow_raw_certificate.wait(5):
            raise TimeoutError("test writer was not released")
        return ready

    monkeypatch.setattr(v285, "_record_snapshot_success", pause_between_canonical_and_raw)

    def publish():
        try:
            v286._record_snapshot_success(broker, rows)
        except Exception as exc:
            errors.append(exc)

    def validate():
        reader_started.set()
        try:
            results.append(v98._publish_v285_snapshot_if_loaded(broker, rows))
        except Exception as exc:
            errors.append(exc)
        finally:
            reader_done.set()

    writer = threading.Thread(target=publish)
    reader = threading.Thread(target=validate)
    writer.start()
    try:
        assert canonical_published.wait(5), "writer did not reach publication barrier"
        reader.start()
        assert reader_started.wait(5), "reader did not begin"
        # Without a common reader/writer lock, v315 sees the mismatch and
        # rejects this otherwise valid authenticated Balance publication.
        assert not reader_done.wait(0.15), "reader observed half-published proof"
    finally:
        allow_raw_certificate.set()
        writer.join(timeout=5)
        if reader.ident is not None:
            reader.join(timeout=5)
    assert not writer.is_alive()
    assert not reader.is_alive()
    assert not errors
    assert results == [True]
    assert broker._nija_authoritative_position_snapshot_generation_v285 == first_generation + 1
    assert broker._nija_authoritative_position_raw_generation_v286 == first_generation + 1


def test_missing_kraken_certificate_cannot_be_published_by_v315():
    broker = _broker()
    rows = _rows()
    assert v285._record_snapshot_success(broker, rows)
    generation = broker._nija_authoritative_position_snapshot_generation_v285
    assert v98._publish_v285_snapshot_if_loaded(broker, rows) is False
    assert broker._nija_authoritative_position_snapshot_generation_v285 == generation
    assert not hasattr(broker, "_nija_authoritative_position_raw_generation_v286")


def test_raw_certificate_publication_failure_revokes_snapshot(monkeypatch):
    class Broker:
        connected = True
        broker_type = "kraken"

        def __setattr__(self, name, value):
            if name == "_nija_authoritative_position_raw_generation_v286":
                raise OSError("cannot publish raw generation")
            object.__setattr__(self, name, value)

    broker = Broker()
    with pytest.raises(RuntimeError, match="kraken_raw_snapshot_publication_failed"):
        v286._record_snapshot_success(broker, _rows())
    assert broker._nija_authoritative_position_snapshot_fetch_ok_v285 is False
    assert not v285._snapshot_status(broker)[0]
