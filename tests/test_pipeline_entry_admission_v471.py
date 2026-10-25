"""Opening orders require an installed trusted durable admission boundary."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot.execution_pipeline import ExecutionPipeline
from bot.order_admission_policy import Candidate


class PipelineAdmissionTests(unittest.TestCase):
    def test_missing_collector_blocks_entry_before_router(self):
        pipeline = object.__new__(ExecutionPipeline)
        pipeline._ecel_required = True
        pipeline._account_order_admission = None
        pipeline._trusted_entry_candidate_provider = None
        pipeline._multi_router = Mock()
        pipeline._router = Mock()
        request = SimpleNamespace(
            symbol="BTC-USD", side="buy", size_usd=10.0,
            intent_type="entry", reduce_only=False, position_effect="open",
            validated=True,
        )
        providers = (
            None,
            Mock(return_value=None),
            Mock(return_value={"account": "platform:kraken"}),
            Mock(return_value=Candidate("platform:kraken", "offline-credential", 1, "a" * 64)),
            Mock(side_effect=RuntimeError("offline_provider_failure")),
        )
        for provider in providers:
            with self.subTest(provider=provider):
                pipeline._trusted_entry_candidate_provider = provider
                with (
                    patch("bot.execution_pipeline.runtime_authority_snapshot",
                          return_value=SimpleNamespace(dispatch_enabled=True)),
                    patch.object(ExecutionPipeline, "_deny", return_value="blocked") as deny,
                ):
                    result = pipeline._dispatch(request, time.monotonic())
                self.assertEqual(result, "blocked")
                deny.assert_called_once()
                self.assertIn("authenticated_reservation_unavailable", deny.call_args.args[2])
                self.assertEqual(pipeline._multi_router.mock_calls, [])
                self.assertEqual(pipeline._router.mock_calls, [])
                if provider is not None:
                    provider.assert_called_once_with(request)


if __name__ == "__main__":
    unittest.main()
