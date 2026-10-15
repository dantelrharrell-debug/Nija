"""Regression: v312 handoff is the single authoritative snapshot publisher."""
import threading
import unittest
from unittest import mock

from bot import runtime_kraken_balance_epoch_handoff_v312_patch as v312
from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286


class HandoffPublicationTests(unittest.TestCase):
    def setUp(self):
        self.broker = mock.Mock()
        self.broker.account_identifier = "test-account"
        self.flight = {"event": threading.Event(), "started_at": 123.0}
        self.rows = [{"symbol": "BTC-USD", "quantity": 0.1}]
        self.observation = {"response": {"error": [], "result": {"XXBT": "0.1"}}, "age_s": 0.1}

    def test_v312_publishes_once_before_handoff_returns(self):
        sequence = []
        with mock.patch.dict(v286.os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}), \
             mock.patch.object(v312, "_fresh_observation", return_value=self.observation), \
             mock.patch.object(v286, "_build_authoritative_rows", return_value=self.rows), \
             mock.patch.object(v286, "_record_snapshot_success", side_effect=lambda *args: sequence.append("publish")), \
             mock.patch.object(v312, "_log_handoff", side_effect=lambda *args: sequence.append("log")):
            self.assertEqual(v286._balance_rows_while_waiting(self.broker, self.flight), self.rows)
        self.assertEqual(sequence, ["publish", "log"])

    def test_missing_observation_never_publishes(self):
        with mock.patch.dict(v286.os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}), \
             mock.patch.object(v312, "_fresh_observation", return_value=None), \
             mock.patch.object(v286, "_record_snapshot_success") as publish:
            self.assertIsNone(v286._balance_rows_while_waiting(self.broker, self.flight))
            publish.assert_not_called()

    def test_publication_failure_fails_closed(self):
        with mock.patch.dict(v286.os.environ, {"NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY": "1"}), \
             mock.patch.object(v312, "_fresh_observation", return_value=self.observation), \
             mock.patch.object(v286, "_build_authoritative_rows", return_value=self.rows), \
             mock.patch.object(v286, "_record_snapshot_success", side_effect=RuntimeError("publish failed")), \
             mock.patch.object(v312, "_log_handoff") as log:
            self.assertIsNone(v286._balance_rows_while_waiting(self.broker, self.flight))
            log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
