from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace


def _patch():
    return importlib.import_module("bot.runtime_terminal_exit_alias_quality_v350_patch")


def test_legacy_pipeline_identity_blocks_ecel_oversell():
    p = _patch()
    fake = ModuleType("execution_pipeline")

    class PipelineResult:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ExecutionPipeline:
        def _log_ecel_final_order(self, request, compiled):
            return None

        def _gate_broker_capabilities(self, request, t_start):
            return PipelineResult(success=True, symbol=request.symbol, side=request.side, size_usd=request.size_usd)

    fake.PipelineResult = PipelineResult
    fake.ExecutionPipeline = ExecutionPipeline

    assert p._patch_pipeline_module(fake) is True
    obj = ExecutionPipeline()
    req = SimpleNamespace(
        strategy="UniversalProtectiveExit:long",
        symbol="ORCA-USD",
        side="sell",
        size_usd=5.028,
        account_id="daivon_frazier",
        intent_type="exit",
        position_effect="close",
        metadata={
            "closing_position": True,
            "protective_exit": True,
            "exit_origin": "universal_v67",
            "verified_position_quantity": 3.00125809,
        },
    )
    compiled = SimpleNamespace(
        accepted=True,
        compiled_base_size=4.0,
        compiled_price_usd=1.257,
        reason="accepted",
    )
    obj._log_ecel_final_order(req, compiled)
    result = obj._gate_broker_capabilities(req, 0.0)
    assert result.success is False
    assert "EXIT_BELOW_EXCHANGE_MIN_AFTER_HOLDINGS_CAP" in result.error
    assert "oversell_blocked=true" in result.error


def test_protective_exit_skips_only_execution_quality_optimizer():
    p = _patch()
    fake = ModuleType("bot.multi_broker_execution_router")

    class MultiBrokerExecutionRouter:
        def route(self, request):
            return {
                "skip_quality_filter": bool(getattr(request, "skip_quality_filter", False)),
                "verified": request.metadata.get("verified_position_quantity"),
            }

    fake.MultiBrokerExecutionRouter = MultiBrokerExecutionRouter
    assert p._patch_router_module(fake) is True

    request = SimpleNamespace(
        symbol="PROVE-USD",
        side="sell",
        metadata={
            "closing_position": True,
            "protective_exit": True,
            "exit_origin": "universal_v67",
            "verified_position_quantity": 11.71387,
        },
    )
    result = MultiBrokerExecutionRouter().route(request)
    assert result["skip_quality_filter"] is True
    assert result["verified"] == 11.71387
    assert not hasattr(request, "skip_quality_filter")


def test_ordinary_entry_does_not_skip_execution_quality_optimizer():
    p = _patch()
    fake = ModuleType("bot.multi_broker_execution_router.entry")

    class MultiBrokerExecutionRouter:
        def route(self, request):
            return bool(getattr(request, "skip_quality_filter", False))

    fake.MultiBrokerExecutionRouter = MultiBrokerExecutionRouter
    assert p._patch_router_module(fake) is True

    request = SimpleNamespace(
        symbol="ETH-USD",
        side="buy",
        metadata={"verified_position_quantity": 1.0},
    )
    assert MultiBrokerExecutionRouter().route(request) is False


def test_verified_protective_close_requires_authoritative_quantity():
    p = _patch()
    request = SimpleNamespace(
        side="sell",
        intent_type="exit",
        position_effect="close",
        metadata={
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
            "verified_position_quantity": 0.0,
        },
    )
    assert p._verified_protective_close(request)[0] is False


def test_manifest_registration_uses_v350_ready_flag():
    p = _patch()
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS")
    old = dict(required)
    try:
        assert p._register_manifest() is True
        assert required["runtime_terminal_exit_alias_quality_v350"] == p._READY_FLAG
    finally:
        required.clear()
        required.update(old)
