from __future__ import annotations

import importlib.util
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "position_cost_basis_legacy_under_test",
        BOT_DIR / "position_cost_basis_legacy_repair_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_positive_nija_strategy_entry_is_preserved_as_legacy_execution():
    module = _load()
    assert module._legacy_execution_verified({
        "entry_price": 125.50,
        "position_source": "nija_strategy",
        "strategy": "APEX_v7.1",
    }) is True


def test_startup_adoption_is_not_promoted_to_verified_cost_basis():
    module = _load()
    assert module._legacy_execution_verified({
        "entry_price": 125.50,
        "position_source": "broker_existing",
        "strategy": "STARTUP_SYNC",
    }) is False


def test_explicit_unverified_flag_wins_over_legacy_inference():
    module = _load()
    assert module._legacy_execution_verified({
        "entry_price": 125.50,
        "position_source": "nija_strategy",
        "strategy": "APEX_v7.1",
        "cost_basis_verified": False,
    }) is False
