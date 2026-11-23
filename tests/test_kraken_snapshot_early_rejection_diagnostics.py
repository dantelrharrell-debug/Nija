"""Synthetic, actual-module checks for Kraken early-rejection diagnostics.

No broker connection, credentials, or production records are used.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from bot import position_sync_failure_truth_v98_patch as v98
from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286


def _rows(quantity=0.25):
    return [{
        "symbol": "BTC-USD", "quantity": quantity, "entry_price": 50000,
        "cost_basis": 50000 * quantity, "tradable": True,
        "pricing_verified": True, "raw_asset": "XXBT",
        "authoritative_balance": True,
    }]


def _broker():
    return SimpleNamespace(connected=True, broker_type="kraken")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda broker: setattr(broker, "_nija_authoritative_position_raw_generation_v286", 0), "generation_invalid_or_mismatch"),
        (lambda broker: setattr(broker, "_nija_authoritative_position_raw_rows_v286", ()), "raw_rows_shape_or_count_mismatch"),
        (lambda broker: setattr(broker, "_nija_authoritative_position_raw_rows_v286", ("invalid",)), "raw_row_invalid"),
    ],
)
def test_early_rejection_logs_reason_without_evidence(caplog, mutation, reason):
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    mutation(broker)
    with caplog.at_level(logging.WARNING):
        assert v98._publish_v285_snapshot_if_loaded(broker, rows) is False
    messages = [record.getMessage() for record in caplog.records]
    assert any("KRAKEN_SNAPSHOT_REUSE_EARLY_REJECTED reason=" + reason in msg for msg in messages)
    assert all("BTC-USD" not in msg and "XXBT" not in msg for msg in messages)


def test_different_authenticated_response_logs_raw_mismatch(caplog):
    broker = _broker()
    v286._record_snapshot_success(broker, _rows())
    with caplog.at_level(logging.WARNING):
        assert v98._publish_v285_snapshot_if_loaded(broker, _rows(0.5)) is False
    assert any(
        "KRAKEN_SNAPSHOT_REUSE_EARLY_REJECTED reason=raw_rows_mismatch" in record.getMessage()
        for record in caplog.records
    )


def test_matching_snapshot_remains_accepted_without_early_rejection(caplog):
    broker = _broker()
    rows = _rows()
    v286._record_snapshot_success(broker, rows)
    with caplog.at_level(logging.WARNING):
        assert v98._publish_v285_snapshot_if_loaded(broker, rows) is True
    assert not any(
        "KRAKEN_SNAPSHOT_REUSE_EARLY_REJECTED" in record.getMessage()
        for record in caplog.records
    )
