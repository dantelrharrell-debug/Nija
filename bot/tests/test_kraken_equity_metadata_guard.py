from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


BOT_DIR = Path(__file__).resolve().parents[1]


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "kraken_equity_metadata_guard_under_test",
        BOT_DIR / "kraken_equity_metadata_guard_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_equity_fields_are_not_assets():
    guard = _load_guard()
    raw = {
        "SOL": 1.25,
        "CANONICAL_EQUITY": 230.97,
        "HELD_EXCLUDED_FROM_EQUITY_SUM": 15.79,
        "TOTAL_FUNDS": 230.97,
        "BROKER_COUNT": 1,
    }
    assert guard._filter_assets(raw) == {"SOL": 1.25}
    assert guard._is_metadata_key("canonical_equity") is True
    assert guard._is_metadata_key("SOL") is False


def test_canonical_total_does_not_add_held_again():
    guard = _load_guard()
    equity = ModuleType("fake_equity")
    equity._direct_total_from_payload = lambda payload: float(payload.get("eb", 0.0))
    equity._cash_from_payload = lambda payload: float(payload.get("cash", 0.0))

    payload = {
        "cash": 72.6069,
        "total_held": 15.7977,
        "non_usd_usd": 15.93517151,
        "eb": 93.2985,
    }
    positions = [{"size_usd": 15.93517151}]
    total = guard._canonical_total(equity, payload, positions)
    assert abs(total - 93.2985) < 1e-9
    assert total < 104.33977151


def test_patch_filters_enriched_payload_before_position_building():
    guard = _load_guard()
    equity = ModuleType("fake_equity")
    equity._NON_ASSET_BALANCE_KEYS = set()
    equity._extract_raw_balances = lambda payload: dict(payload)
    equity._build_positions = lambda instance, assets: sorted(assets)
    equity._direct_total_from_payload = lambda payload: 0.0
    equity._cash_from_payload = lambda payload: 10.0
    equity._payload_total_equity = lambda payload, positions: 999.0

    assert guard._patch_equity_module(equity) is True
    assets = equity._extract_raw_balances({"SOL": 2.0, "canonical_equity": 230.0})
    assert assets == {"SOL": 2.0}
    assert equity._build_positions(object(), {"SOL": 2.0, "CANONICAL_EQUITY": 230.0}) == ["SOL"]
    assert equity._payload_total_equity({"non_usd_usd": 5.0, "total_held": 5.0}, []) == 15.0
