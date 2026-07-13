from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BOT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guards = load_module(
    "kraken_exit_final_guards_under_test",
    "kraken_exit_final_guards_patch.py",
)


class TestVerifiedCostBasis:
    def test_explicitly_unverified_position_cannot_trigger_profit_exit(self):
        module = types.ModuleType("bot.kraken_all_account_exit_runtime_patch")
        module._exit_reason = lambda position, price, account, symbol: (
            "net_profit_target", 100.8, 101.2
        )
        assert guards._patch_exit_decision(module)

        result = module._exit_reason(
            {
                "entry_price": 100.0,
                "cost_basis_verified": False,
                "auto_exit_blocked": True,
                "auto_exit_block_reason": "unverified_cost_basis",
            },
            102.0,
            "user:tania_gilbert:kraken",
            "AIR-EUR",
        )
        assert result == (None, 0.0, 0.0)

    def test_verified_position_reaches_normal_exit_policy(self):
        module = types.ModuleType("bot.kraken_all_account_exit_runtime_patch.verified")
        module._exit_reason = lambda position, price, account, symbol: (
            "fee_adjusted_break_even", 100.8, 101.2
        )
        assert guards._patch_exit_decision(module)
        assert module._exit_reason(
            {"entry_price": 100.0, "cost_basis_verified": True},
            100.9,
            "platform:kraken",
            "SOL-USD",
        )[0] == "fee_adjusted_break_even"


class TestWriterAuthorizedStateGate:
    @staticmethod
    def _pipeline_module():
        class ExecutionPipeline:
            def _enforce_execution_gate(self, request, t_start):
                return "state_gate_blocked"

        module = types.ModuleType("bot.execution_pipeline")
        module.ExecutionPipeline = ExecutionPipeline
        return module

    @staticmethod
    def _request(intent="exit"):
        return SimpleNamespace(
            intent_type=intent,
            position_effect="close" if intent == "exit" else None,
            metadata={"closing_position": intent == "exit"},
            account_id="tania_gilbert",
            symbol="AIR-EUR",
            side="sell",
        )

    def test_live_exit_bypasses_entry_state_only_after_writer_verification(self):
        module = self._pipeline_module()
        assert guards._patch_execution_gate(module)

        authority = types.ModuleType("bot.execution_authority_context")
        authority.assert_distributed_writer_authority = lambda: None
        fake_bot = types.ModuleType("bot")
        fake_bot.__path__ = []
        fake_bot.execution_authority_context = authority

        with patch.dict(
            sys.modules,
            {"bot": fake_bot, "bot.execution_authority_context": authority},
            clear=False,
        ), patch.dict(
            os.environ,
            {"DRY_RUN_MODE": "false", "PAPER_MODE": "false", "APP_STORE_MODE": "false"},
            clear=False,
        ):
            pipeline = module.ExecutionPipeline()
            assert pipeline._enforce_execution_gate(self._request("exit"), 0.0) is None
            assert pipeline._enforce_execution_gate(self._request("entry"), 0.0) == "state_gate_blocked"

    def test_missing_writer_authority_keeps_state_gate_blocked(self):
        module = self._pipeline_module()
        assert guards._patch_execution_gate(module)

        authority = types.ModuleType("bot.execution_authority_context")

        def reject():
            raise RuntimeError("writer lease unavailable")

        authority.assert_distributed_writer_authority = reject
        fake_bot = types.ModuleType("bot")
        fake_bot.__path__ = []
        fake_bot.execution_authority_context = authority

        with patch.dict(
            sys.modules,
            {"bot": fake_bot, "bot.execution_authority_context": authority},
            clear=False,
        ), patch.dict(
            os.environ,
            {"DRY_RUN_MODE": "false", "PAPER_MODE": "false", "APP_STORE_MODE": "false"},
            clear=False,
        ):
            pipeline = module.ExecutionPipeline()
            assert pipeline._enforce_execution_gate(self._request("exit"), 0.0) == "state_gate_blocked"

    def test_dry_run_exit_is_not_promoted_to_live(self):
        module = self._pipeline_module()
        assert guards._patch_execution_gate(module)
        with patch.dict(os.environ, {"DRY_RUN_MODE": "true"}, clear=False):
            pipeline = module.ExecutionPipeline()
            assert pipeline._enforce_execution_gate(self._request("exit"), 0.0) == "state_gate_blocked"
