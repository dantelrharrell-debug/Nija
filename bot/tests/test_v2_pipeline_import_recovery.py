"""Fail-closed regression coverage for V2 execution-pipeline recovery."""

import unittest
from dataclasses import dataclass
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

    def test_rebinds_stale_execution_pipeline_fallback_to_canonical_contract(self) -> None:
        @dataclass(frozen=True)
        class StalePipelineRequest:
            symbol: str = ""
            side: str = "buy"
            size_usd: float = 0.0

        canonical = __import__(
            "bot.pipeline_request_contract",
            fromlist=["PipelineRequest"],
        ).PipelineRequest
        recovered_getter = object()

        def import_module(name):
            if name in {"bot.pipeline_request_contract", "pipeline_request_contract"}:
                return SimpleNamespace(PipelineRequest=canonical)
            if name in {"bot.execution_pipeline", "execution_pipeline"}:
                return SimpleNamespace(
                    PipelineRequest=StalePipelineRequest,
                    get_execution_pipeline=recovered_getter,
                )
            raise ImportError(name)

        with patch.object(submitter, "PipelineRequest", StalePipelineRequest), \
             patch.object(submitter, "get_execution_pipeline", recovered_getter), \
             patch.object(submitter.importlib, "import_module", side_effect=import_module):
            request_type, pipeline_getter = submitter._resolve_execution_pipeline_dependencies()

        self.assertIs(request_type, canonical)
        self.assertIs(pipeline_getter, recovered_getter)
        self.assertIn("limit_price", request_type.__dataclass_fields__)
        self.assertIn("intent_type", request_type.__dataclass_fields__)

    def test_base_sized_exit_uses_canonical_base_asset_unit_type(self) -> None:
        class Request:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class Pipeline:
            def execute(self, request):
                self.request = request
                return SimpleNamespace(
                    success=False,
                    error="rejected before dispatch",
                    order_id="",
                    fill_price=0.0,
                    filled_size_usd=0.0,
                )

        pipeline = Pipeline()
        broker = SimpleNamespace(
            broker_type="coinbase",
            connected=True,
            get_current_price=lambda symbol: 100.0,
            get_account_balance=lambda: {"available_balance": 1000.0},
        )

        with patch.object(
            submitter,
            "_resolve_execution_pipeline_dependencies",
            return_value=(Request, lambda: pipeline),
        ), patch.object(
            submitter,
            "assert_distributed_writer_authority",
            return_value=None,
        ), patch.object(
            submitter,
            "_resolve_available_balance",
            return_value=1000.0,
        ), patch.object(
            submitter,
            "_prepare_v2_duplicate_handoff",
            return_value=True,
        ):
            submitter.submit_market_order_via_pipeline(
                broker,
                "BTC-USD",
                "sell",
                0.01,
                size_type="base",
                intent_type="exit",
                position_effect="close",
            )

        self.assertEqual(pipeline.request.unit_type, "base_asset")

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
