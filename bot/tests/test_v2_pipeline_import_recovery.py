"""Fail-closed regression coverage for V2 execution-pipeline recovery."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bot.pipeline_order_submitter as submitter


class TestV2PipelineImportRecovery(unittest.TestCase):
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

    def test_import_time_exceptions_retain_owned_reservation_and_fail_closed(self) -> None:
        metadata = {
            "duplicate_key": "v2:lazy-import-failure",
            "duplicate_token": "owned-token",
            "duplicate_shared_required": False,
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
        self.assertTrue(result["v2_pre_submit_proven"])
        requested_modules = [
            call.args[0]
            for call in import_module.call_args_list
            if call.args and call.args[0] in {"bot.execution_pipeline", "execution_pipeline"}
        ]
        self.assertGreaterEqual(
            requested_modules.count("bot.execution_pipeline"),
            1,
        )
        self.assertGreaterEqual(
            requested_modules.count("execution_pipeline"),
            1,
        )
        self.assertTrue(
            all(
                module_name in {"bot.execution_pipeline", "execution_pipeline"}
                for module_name in requested_modules
            )
        )
        finalize.assert_called_once_with(metadata, "released")


if __name__ == "__main__":
    unittest.main()
