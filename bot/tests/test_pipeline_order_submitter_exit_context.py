from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1]


def test_explicit_exit_context_reaches_pipeline_without_platform_balance_leak():
    captured = {}

    class PipelineRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Pipeline:
        def execute(self, request):
            captured["request"] = request
            return SimpleNamespace(
                success=True,
                fill_price=0.011,
                filled_size_usd=request.size_usd,
                broker="kraken",
                error="",
            )

    pipeline = Pipeline()
    execution_pipeline = types.ModuleType("bot.execution_pipeline")
    execution_pipeline.PipelineRequest = PipelineRequest
    execution_pipeline.get_execution_pipeline = lambda: pipeline

    authority_context = types.ModuleType("bot.execution_authority_context")
    authority_context.assert_distributed_writer_authority = lambda: None

    margin_engine = types.ModuleType("bot.kraken_margin_engine")

    @contextmanager
    def margin_account_scope(account_id, adapter=None):
        captured["scope_account"] = account_id
        yield SimpleNamespace()

    margin_engine.margin_account_scope = margin_account_scope

    capital_authority = types.ModuleType("bot.capital_authority")

    class Authority:
        def get_per_broker(self, key):
            # Deliberately expose a platform total.  The submitter must not use it
            # to size an explicit user exit.
            return 225.0 if key == "kraken" else 0.0

        def is_registered(self, key):
            return key == "kraken"

    capital_authority.get_capital_authority = lambda: Authority()

    fake_bot = types.ModuleType("bot")
    fake_bot.__path__ = []
    fake_bot.execution_pipeline = execution_pipeline
    fake_bot.execution_authority_context = authority_context
    fake_bot.kraken_margin_engine = margin_engine
    fake_bot.capital_authority = capital_authority

    root_capital_authority = types.ModuleType("capital_authority")
    root_capital_authority.get_capital_authority = capital_authority.get_capital_authority

    modules = {
        "bot": fake_bot,
        "bot.execution_pipeline": execution_pipeline,
        "bot.execution_authority_context": authority_context,
        "bot.kraken_margin_engine": margin_engine,
        "bot.capital_authority": capital_authority,
        "capital_authority": root_capital_authority,
    }

    with patch.dict(sys.modules, modules, clear=False):
        spec = importlib.util.spec_from_file_location(
            "pipeline_order_submitter_exit_under_test",
            BOT_DIR / "pipeline_order_submitter.py",
        )
        assert spec is not None and spec.loader is not None
        submitter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(submitter)

        class KrakenBroker:
            NAME = "Kraken"
            broker_type = SimpleNamespace(value="kraken")
            account_identifier = "USER:tania_gilbert"
            _last_known_balance = 104.31

            def get_current_price(self, symbol):
                assert symbol == "AIREUR"
                return 0.011

        result = submitter.submit_market_order_via_pipeline(
            broker=KrakenBroker(),
            symbol="AIREUR",
            side="sell",
            quantity=100.0,
            size_type="base",
            strategy="KrakenAccountExit:fee_adjusted_break_even",
            intent_type="exit",
            account_id_override="tania_gilbert",
            position_effect="close",
            metadata_override={"closing_position": True},
        )

    request = captured["request"]
    assert result["status"] == "filled"
    assert request.account_id == "tania_gilbert"
    assert request.intent_type == "exit"
    assert request.position_effect == "close"
    assert request.side == "sell"
    assert request.available_balance_usd == 104.31
    assert request.available_balance_usd != 225.0
    assert request.metadata["closing_position"] is True
    assert captured["scope_account"] == "tania_gilbert"
