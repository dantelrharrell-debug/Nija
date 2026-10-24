"""Opening orders require an installed trusted durable admission boundary."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.execution_pipeline import ExecutionPipeline


class PipelineAdmissionTests(unittest.TestCase):
    def test_missing_collector_blocks_entry_before_router(self):
        pipeline = object.__new__(ExecutionPipeline)
        pipeline._account_order_admission = None
        pipeline._trusted_entry_candidate_provider = None
        request = SimpleNamespace(
            symbol="BTC-USD", side="buy", size_usd=10.0,
            intent_type="entry", reduce_only=False, position_effect="open",
        )
        with patch.object(ExecutionPipeline, "_deny", return_value="blocked") as deny:
            result = pipeline._dispatch(request, time.monotonic())
        self.assertEqual(result, "blocked")
        self.assertIn("authenticated_reservation_unavailable", deny.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
