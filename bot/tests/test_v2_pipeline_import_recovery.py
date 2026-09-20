"""Fail-closed regression coverage for V2 execution-pipeline recovery."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bot.pipeline_order_submitter as submitter


class TestV2PipelineImportRecovery(unittest.TestCase):
    def test_incomplete_reservation_handle_blocks_before_pipeline_resolution(self) -> None:
        broker = SimpleNamespace(broker_name="coinbase", connected=True)
        with patch.object(submitter, "_resolve_execution_pipeline_dependencies") as resolve:
            result = submitter.submit_market_order_via_pipeline(
                broker,
                "BTC-USD",
                "buy",
                10.0,
                metadata_override={"duplicate_key": "v2:missing-token"},
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "Incomplete V2 reservation handle")
        resolve.assert_not_called()

    def test_recovers_dependencies_after_circular_startup(self) -> None:
        recovered_request_type = object()
        recovered_getter = object()
        recovered_module = SimpleNamespace(
            PipelineRequest=recovered_request_type,
            get_execution_pipeline=recovered_getter,
        )

        with patch.object(submitter, "PipelineRequest", None), \
             patch.object(submitter, "get_execution_pipeline", None), \
             patch.object(submitter.importlib, "import_module", return_value=recovered_module):
            request_type, pipeline_getter = submitter._resolve_execution_pipeline_dependencies()

            self.assertIs(request_type, recovered_request_type)
            self.assertIs(pipeline_getter, recovered_getter)
            self.assertIs(submitter.PipelineRequest, recovered_request_type)
            self.assertIs(submitter.get_execution_pipeline, recovered_getter)

    def test_preserves_injected_dependency_when_only_one_is_missing(self) -> None:
        injected_request_type = object()
        recovered_getter = object()
        recovered_module = SimpleNamespace(
            PipelineRequest=object(),
            get_execution_pipeline=recovered_getter,
        )

        with patch.object(submitter, "PipelineRequest", injected_request_type), \
             patch.object(submitter, "get_execution_pipeline", None), \
             patch.object(submitter.importlib, "import_module", return_value=recovered_module):
            request_type, pipeline_getter = submitter._resolve_execution_pipeline_dependencies()

            self.assertIs(request_type, injected_request_type)
            self.assertIs(pipeline_getter, recovered_getter)

    def test_import_time_exceptions_release_reservation_and_fail_closed(self) -> None:
        metadata = {
            "duplicate_key": "v2:lazy-import-failure",
            "duplicate_token": "owner-token",
        }
        broker = SimpleNamespace(broker_name="coinbase", connected=True)

        with patch.object(submitter, "PipelineRequest", None), \
             patch.object(submitter, "get_execution_pipeline", None), \
             patch.object(
                 submitter.importlib,
                 "import_module",
                 side_effect=(AttributeError("partial canonical module"), NameError("partial fallback module")),
             ) as import_module, \
             patch.object(submitter, "_finalize_v2_duplicate") as finalize:
            result = submitter.submit_market_order_via_pipeline(
                broker,
                "BTC-USD",
                "buy",
                10.0,
                metadata_override=metadata,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "ExecutionPipeline unavailable")
        self.assertEqual(import_module.call_count, 2)
        finalize.assert_called_once_with(metadata, "released")

    def test_partial_alias_is_not_cached_before_later_canonical_recovery(self) -> None:
        stale_request_type = object()
        recovered_request_type = object()
        recovered_getter = object()
        partial_alias = SimpleNamespace(PipelineRequest=stale_request_type)
        recovered_module = SimpleNamespace(
            PipelineRequest=recovered_request_type,
            get_execution_pipeline=recovered_getter,
        )

        with patch.object(submitter, "PipelineRequest", None), \
             patch.object(submitter, "get_execution_pipeline", None), \
             patch.object(
                 submitter.importlib,
                 "import_module",
                 side_effect=(AttributeError("partial canonical module"), partial_alias, recovered_module),
             ):
            first_request, first_getter = submitter._resolve_execution_pipeline_dependencies()
            self.assertIsNone(first_request)
            self.assertIsNone(first_getter)
            self.assertIsNone(submitter.PipelineRequest)

            request_type, pipeline_getter = submitter._resolve_execution_pipeline_dependencies()
            self.assertIs(request_type, recovered_request_type)
            self.assertIs(pipeline_getter, recovered_getter)
            self.assertIsNot(request_type, stale_request_type)


if __name__ == "__main__":
    unittest.main()
