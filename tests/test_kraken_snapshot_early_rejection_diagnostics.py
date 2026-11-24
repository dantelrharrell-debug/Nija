"""Actual v98 guard regression tests; no broker I/O or credentials."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

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


class KrakenEarlyRejectionTests(unittest.TestCase):
    def _reject(self, broker, authority, rows, reason):
        with self.assertLogs(v98.LOGGER, level="WARNING") as captured:
            self.assertFalse(
                v98._reuse_exact_kraken_snapshot_locked(broker, rows, authority)
            )
        self.assertTrue(any(
            "KRAKEN_SNAPSHOT_REUSE_EARLY_REJECTED reason=" + reason in msg
            for msg in captured.output
        ))
        self.assertTrue(all("TEST_ASSET" not in msg for msg in captured.output))

    def test_generation_mismatch(self):
        broker, authority, rows = _fixture()
        broker._nija_authoritative_position_raw_generation_v286 = 6
        self._reject(broker, authority, rows, "generation_invalid_or_mismatch")

    def test_raw_count_mismatch(self):
        broker, authority, rows = _fixture()
        broker._nija_authoritative_position_raw_rows_v286 = ()
        self._reject(broker, authority, rows, "raw_rows_shape_or_count_mismatch")

    def test_malformed_raw_row(self):
        broker, authority, rows = _fixture()
        broker._nija_authoritative_position_raw_rows_v286 = ("invalid",)
        self._reject(broker, authority, rows, "raw_row_invalid")

    def test_different_returned_rows(self):
        broker, authority, _ = _fixture()
        self._reject(broker, authority, _rows(2), "raw_rows_mismatch")

    def test_exact_snapshot_accepted(self):
        broker, authority, rows = _fixture()
        with self.assertNoLogs(v98.LOGGER, level="WARNING"):
            self.assertTrue(
                v98._reuse_exact_kraken_snapshot_locked(broker, rows, authority)
            )


if __name__ == "__main__":
    unittest.main()
