import os
import re
import time
import types
import unittest
from enum import Enum
from pathlib import Path
from unittest.mock import patch

from bot.execution_pipeline import ExecutionPipeline, PipelineRequest, PipelineResult


class _TradingMode(Enum):
    LIVE = "live"
    MONITOR = "monitor"
    DISABLED = "disabled"
    APP_STORE = "app_store"
    DRY_RUN = "dry_run"


class _FakeSafetyController:
    def __init__(self, mode: _TradingMode, allowed: bool, reason: str) -> None:
        self._mode = mode
        self._allowed = allowed
        self._reason = reason

    def recheck_mode(self) -> None:
        return None

    def get_current_mode(self) -> _TradingMode:
        return self._mode

    def is_trading_allowed(self):
        return self._allowed, self._reason


def _request() -> PipelineRequest:
    return PipelineRequest(symbol="BTC-USD", side="buy", size_usd=25.0)


class TestPr2009ReviewComments(unittest.TestCase):
    def test_force_trade_bypasses_monitor_safety_denial(self) -> None:
        safety = _FakeSafetyController(_TradingMode.MONITOR, allowed=False, reason="monitor mode")
        fake_mod = types.SimpleNamespace(
            get_safety_controller=lambda: safety,
            TradingMode=_TradingMode,
        )
        fake_self = types.SimpleNamespace(_simulate_execution=lambda *_args, **_kwargs: None)

        with patch("bot.execution_pipeline._try_import", return_value=fake_mod):
            with patch.dict(os.environ, {"FORCE_TRADE": "true", "FORCE_TRADE_MODE": ""}, clear=False):
                result = ExecutionPipeline._enforce_execution_gate(fake_self, _request(), time.monotonic())

        self.assertIsNone(result)

    def test_without_force_trade_monitor_mode_remains_blocked(self) -> None:
        safety = _FakeSafetyController(_TradingMode.MONITOR, allowed=False, reason="monitor mode")
        fake_mod = types.SimpleNamespace(
            get_safety_controller=lambda: safety,
            TradingMode=_TradingMode,
        )
        fake_self = types.SimpleNamespace(_simulate_execution=lambda *_args, **_kwargs: None)

        with patch("bot.execution_pipeline._try_import", return_value=fake_mod):
            with patch.dict(os.environ, {"FORCE_TRADE": "false", "FORCE_TRADE_MODE": ""}, clear=False):
                result = ExecutionPipeline._enforce_execution_gate(fake_self, _request(), time.monotonic())

        self.assertIsInstance(result, PipelineResult)
        self.assertFalse(result.success)
        self.assertIn("monitor mode", result.error)

    def test_force_trade_direct_short_capability_defaults_fail_closed(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "nija_core_loop.py").read_text(encoding="utf-8")
        self.assertIn("_ft_broker_can_short = False", text)
        self.assertRegex(text, r"conservative:\s*assume short is NOT supported")


if __name__ == "__main__":
    unittest.main()
