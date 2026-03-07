"""
Import Smoke Test
=================

Verifies that all new NIJA modules can be imported without errors.
Run with: pytest tests/imports_smoke_test.py

These tests are intentionally lightweight — they only check that Python
can parse and load each module without raising ImportError or SyntaxError.
"""

import importlib
import sys
from pathlib import Path

import pytest

# Ensure the bot package is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))


NEW_MODULES = [
    "bot.stress_test_engine",
    "bot.portfolio_risk_tuner",
    "bot.multi_venue_calibrator",
    "bot.rl_validation_engine",
    "bot.alert_manager",
    "bot.incremental_deployer",
    "bot.hedge_fund_analytics",
]

EXISTING_MODULES = [
    "bot.paper_trading",
    "bot.monitoring_system",
    "bot.risk_alarm_system",
    "bot.portfolio_var_monitor",
    "bot.execution_optimizer",
    "bot.risk_dashboard",
    "bot.global_risk_controller",
    "bot.portfolio_intelligence",
    "bot.self_learning_strategy_allocator",
    "bot.live_rl_feedback",
    "bot.monte_carlo_stress_test",
    "bot.liquidity_stress_testing",
    "bot.broker_adapters",
]


@pytest.mark.parametrize("module_name", NEW_MODULES)
def test_new_module_imports(module_name: str) -> None:
    """Each new module must import without raising any exception."""
    mod = importlib.import_module(module_name)
    assert mod is not None, f"Module {module_name} imported as None"


@pytest.mark.parametrize("module_name", EXISTING_MODULES)
def test_existing_module_imports(module_name: str) -> None:
    """Key existing modules must continue to import cleanly."""
    try:
        mod = importlib.import_module(module_name)
        assert mod is not None
    except ImportError as exc:
        # Some modules have optional heavy dependencies (e.g. coinbase SDK).
        # We allow ImportError for existing modules but not for new ones.
        pytest.skip(f"Skipped {module_name}: {exc}")
