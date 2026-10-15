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


if __name__ == "__main__":
    unittest.main()
