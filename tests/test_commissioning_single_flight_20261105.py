"""Single-flight commissioning admission must never consume twice."""
import threading
import unittest
from unittest.mock import Mock, patch

from bot.account_order_admission import AdmissionDenied
from bot.commissioning_runtime import CommissioningDispatchAdapter


class CandidateStub:
    pass


class CommissioningSingleFlightTests(unittest.TestCase):
    def make_adapter(self):
        candidate = CandidateStub()
        gate = Mock()
        adapter = CommissioningDispatchAdapter(
            gate=gate,
            plan=object(),
            candidate_for_request=lambda request: candidate,
            enabled=True,
        )
        adapter.validate_pipeline_request = Mock()
        return adapter, gate

    def test_second_consume_does_not_touch_durable_gate(self):
        adapter, gate = self.make_adapter()
        with patch("bot.commissioning_runtime.Candidate", CandidateStub):
            adapter.consume(object())
            with self.assertRaisesRegex(AdmissionDenied, "already_armed"):
                adapter.consume(object())
        gate.consume_first_trade.assert_called_once()

    def test_concurrent_consumers_cannot_both_pass(self):
        adapter, gate = self.make_adapter()
        barrier = threading.Barrier(3)
        outcomes = []
        def run():
            barrier.wait()
            try:
                adapter.consume(object())
                outcomes.append("admitted")
            except AdmissionDenied:
                outcomes.append("denied")
        with patch("bot.commissioning_runtime.Candidate", CandidateStub):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=5)
        self.assertEqual(sorted(outcomes), ["admitted", "denied"])
        gate.consume_first_trade.assert_called_once()


if __name__ == "__main__":
    unittest.main()
