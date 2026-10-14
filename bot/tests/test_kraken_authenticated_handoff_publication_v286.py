"""Regression tests: authenticated v312 handoff must publish v285 snapshot."""
import threading
import unittest
from unittest import mock

from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286


class KrakenHandoffPublicationTests(unittest.TestCase):
    def setUp(self):
        self.broker = object()
        self.flight = {"event": threading.Event(), "started_at": 123.0}
        self.rows = [{"symbol": "BTC-USD", "quantity": 0.1, "entry_price": 50000.0}]
        self.observation = {"authenticated": True}

    def _handoff(self, observation, rows):
        v312 = mock.Mock()
        v312._fresh_observation.return_value = observation
        v312._rows_from_observation.return_value = rows
        return v312

    def test_authenticated_handoff_publishes_canonical_snapshot_before_return(self):
        v312 = self._handoff(self.observation, self.rows)
        sequence = []
        def publish(broker, rows):
            sequence.append("published")
            self.assertIs(broker, self.broker)
            self.assertEqual(rows, self.rows)
        def logged(*args):
            sequence.append("logged")
        v312._log_handoff.side_effect = logged
        with mock.patch.dict(v286.os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}), \
             mock.patch.object(v286.importlib, "import_module", return_value=v312), \
             mock.patch.object(v286, "_record_snapshot_success", side_effect=publish):
            self.assertEqual(v286._balance_rows_while_waiting(self.broker, self.flight), self.rows)
        self.assertEqual(sequence, ["published", "logged"])

    def test_missing_authenticated_observation_never_publishes(self):
        v312 = self._handoff(None, self.rows)
        with mock.patch.dict(v286.os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}), \
             mock.patch.object(v286.importlib, "import_module", return_value=v312), \
             mock.patch.object(v286, "_record_snapshot_success") as publish:
            self.assertIsNone(v286._balance_rows_while_waiting(self.broker, self.flight))
            publish.assert_not_called()

    def test_snapshot_publication_error_fails_closed(self):
        v312 = self._handoff(self.observation, self.rows)
        with mock.patch.dict(v286.os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}), \
             mock.patch.object(v286.importlib, "import_module", return_value=v312), \
             mock.patch.object(v286, "_record_snapshot_success", side_effect=RuntimeError("failed")):
            self.assertIsNone(v286._balance_rows_while_waiting(self.broker, self.flight))
            v312._log_handoff.assert_not_called()


if __name__ == "__main__":
    unittest.main()
