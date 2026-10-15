"""Verify v286 snapshot writers serialize and publication failure remains fail-closed."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286


class SnapshotWriterLockTests(unittest.TestCase):
    def test_competing_publishers_cannot_interleave_canonical_and_raw_generation(self):
        broker = SimpleNamespace()
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        generations = []
        calls = []

        def publish(_broker, rows):
            calls.append(rows[0]["symbol"])
            if rows[0]["symbol"] == "FIRST":
                first_entered.set()
                if not release_first.wait(2):
                    raise RuntimeError("test_sync_timeout")
            else:
                second_entered.set()
            current = getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0)
            broker._nija_authoritative_position_snapshot_generation_v285 = current + 1
            generations.append(current + 1)
            return True

        authority = SimpleNamespace(_record_snapshot_success=publish)
        errors = []

        def writer(symbol):
            try:
                v286._record_snapshot_success(broker, [{"symbol": symbol, "quantity": 1}])
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(v286, "_v285", return_value=authority):
            first = threading.Thread(target=writer, args=("FIRST",))
            second = threading.Thread(target=writer, args=("SECOND",))
            first.start()
            self.assertTrue(first_entered.wait(2))
            second.start()
            # The second writer must wait for the first to finish publication.
            self.assertFalse(second_entered.wait(0.05))
            release_first.set()
            first.join(2)
            second.join(2)

        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertFalse(errors)
        self.assertEqual(calls, ["FIRST", "SECOND"])
        self.assertEqual(generations, [1, 2])
        self.assertEqual(broker._nija_authoritative_position_raw_generation_v286, 2)
        self.assertEqual(broker._nija_authoritative_position_raw_rows_v286[0]["symbol"], "SECOND")

    def test_rejected_canonical_publication_never_writes_raw_proof(self):
        broker = SimpleNamespace()
        authority = SimpleNamespace(_record_snapshot_success=lambda *_: False)
        with mock.patch.object(v286, "_v285", return_value=authority):
            with self.assertRaisesRegex(RuntimeError, "v285_authoritative_snapshot_record_failed"):
                v286._record_snapshot_success(broker, [{"symbol": "BTC-USD", "quantity": 1}])
        self.assertFalse(hasattr(broker, "_nija_authoritative_position_raw_generation_v286"))


    def test_raw_field_write_failure_revokes_canonical_proof(self):
        from bot import runtime_authoritative_position_coverage_v285_patch as v285

        class RejectRawField(SimpleNamespace):
            def __setattr__(self, name, value):
                if name == self.__dict__.get("reject_field"):
                    raise OSError("raw_field_is_read_only")
                super().__setattr__(name, value)

        for field in (
            "_nija_authoritative_position_raw_rows_v286",
            "_nija_authoritative_position_raw_generation_v286",
        ):
            with self.subTest(field=field):
                broker = RejectRawField(reject_field=field)
                with (
                    mock.patch.object(v286, "_v285", return_value=v285),
                    mock.patch.object(v285, "_connected", return_value=True),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "v286_raw_snapshot_publication_failed"
                    ):
                        v286._record_snapshot_success(
                            broker, [{"symbol": "BTC-USD", "quantity": 1}]
                        )
                    self.assertIs(
                        getattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285"),
                        False,
                    )
                    self.assertEqual(
                        broker._nija_authoritative_position_snapshot_error_v285,
                        "v286_raw_snapshot_publication_failed",
                    )
                    ready, reason, _rows, _age, _generation = v285._snapshot_status(broker)
                    self.assertFalse(ready)
                    self.assertEqual(reason, "v286_raw_snapshot_publication_failed")

    def test_row_preparation_failure_never_publishes_canonical_success(self):
        broker = SimpleNamespace()
        authority = SimpleNamespace(
            _record_snapshot_success=lambda *_: self.fail("canonical publisher called")
        )
        with mock.patch.object(v286, "_v285", return_value=authority):
            with self.assertRaises(TypeError):
                v286._record_snapshot_success(
                    broker, [{"symbol": "BTC-USD", "quantity": 1}, None]
                )
        self.assertFalse(
            hasattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285")
        )


if __name__ == "__main__":
    unittest.main()
