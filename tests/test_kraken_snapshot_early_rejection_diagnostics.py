"""Actual v98 module tests with synthetic, non-broker snapshot evidence."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from bot import position_sync_failure_truth_v98_patch as v98


def _rows(quantity=1):
    return [{"synthetic_asset": "TEST_ASSET", "quantity": quantity}]


def _fixture():
    rows = _rows()
    broker = SimpleNamespace(
        _nija_authoritative_position_snapshot_generation_v285=7,
        _nija_authoritative_position_raw_generation_v286=7,
        _nija_authoritative_position_raw_rows_v286=tuple(rows),
    )
    authority = SimpleNamespace(
        _snapshot_rows=lambda result: (result, None),
        _snapshot_status=lambda broker: (True, "ok", rows, 0, 7),
    )
    return broker, authority, rows


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda broker: setattr(broker, "_nija_authoritative_position_raw_generation_v286", 6), "generation_invalid_or_mismatch"),
        (lambda broker: setattr(broker, "_nija_authoritative_position_raw_rows_v286", ()), "raw_rows_shape_or_count_mismatch"),
        (lambda broker: setattr(broker, "_nija_authoritative_position_raw_rows_v286", ("invalid",)), "raw_row_invalid"),
    ],
)
def test_early_rejection_reason_without_evidence(caplog, change, reason):
    broker, authority, rows = _fixture()
    change(broker)
    with caplog.at_level(logging.WARNING):
        assert v98._reuse_exact_kraken_snapshot_locked(broker, rows, authority) is False
    messages = [record.getMessage() for record in caplog.records]
    assert any("KRAKEN_SNAPSHOT_REUSE_EARLY_REJECTED reason=" + reason in msg for msg in messages)
    assert all("TEST_ASSET" not in msg for msg in messages)


def test_different_returned_rows_rejected_and_logged(caplog):
    broker, authority, _rows_original = _fixture()
    with caplog.at_level(logging.WARNING):
        assert v98._reuse_exact_kraken_snapshot_locked(broker, _rows(2), authority) is False
    assert any(
        "KRAKEN_SNAPSHOT_REUSE_EARLY_REJECTED reason=raw_rows_mismatch" in record.getMessage()
        for record in caplog.records
    )


def test_exact_snapshot_accepted_without_early_warning(caplog):
    broker, authority, rows = _fixture()
    with caplog.at_level(logging.WARNING):
        assert v98._reuse_exact_kraken_snapshot_locked(broker, rows, authority) is True
    assert not any("KRAKEN_SNAPSHOT_REUSE_EARLY_REJECTED" in record.getMessage() for record in caplog.records)
