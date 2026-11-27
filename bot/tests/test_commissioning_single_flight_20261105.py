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
        entered = threading.Event()
        release = threading.Event()
        contender_waiting = threading.Event()
        outcomes = []
        errors = []
        real_lock = adapter._consumer_lock

        class ObservedConsumerLock:
            def __enter__(self):
                if threading.current_thread().name == "contender":
                    contender_waiting.set()
                real_lock.acquire()

            def __exit__(self, *_):
                real_lock.release()

        adapter._consumer_lock = ObservedConsumerLock()

        def slow_consume(*_):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test_admission_release_timeout")

        gate.consume_first_trade.side_effect = slow_consume

        def run():
            try:
                adapter.consume(object())
                outcomes.append("admitted")
            except AdmissionDenied:
                outcomes.append("denied")
            except BaseException as exc:
                errors.append(exc)

        with patch("bot.commissioning_runtime.Candidate", CandidateStub):
            first = threading.Thread(target=run, name="first")
            contender = threading.Thread(target=run, name="contender")
            first.start()
            try:
                self.assertTrue(entered.wait(2))
                contender.start()
                self.assertTrue(contender_waiting.wait(2))
                self.assertEqual(gate.consume_first_trade.call_count, 1)
            finally:
                release.set()
                first.join(5)
                if contender.ident is not None:
                    contender.join(5)
        self.assertFalse(first.is_alive())
        self.assertFalse(contender.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(outcomes), ["admitted", "denied"])
        gate.consume_first_trade.assert_called_once()


if __name__ == "__main__":
    unittest.main()
