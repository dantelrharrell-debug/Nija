from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "position_tracker_cost_basis_under_test",
        BOT_DIR / "position_tracker.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ENTRY_PRICE_STORE_AVAILABLE = False
    return module


def test_current_price_adoption_mark_is_not_claimed_as_real_entry():
    module = _load()
    with tempfile.TemporaryDirectory() as tmp:
        tracker = module.PositionTracker(str(Path(tmp) / "positions.json"))
        assert tracker.sync_position_snapshot(
            symbol="AAVE-USD",
            quantity=0.03487477,
            entry_price=0.0,
            current_price=175.0,
            size_usd=6.10,
            entry_price_source="override",
        )
        row = tracker.get_position("AAVE-USD")
        assert row["entry_price"] == 175.0
        assert row["entry_price_source"] == "estimated_from_adoption_mark"
        assert row["cost_basis_verified"] is False
        assert row["auto_exit_blocked"] is True
        assert "unverified_cost_basis" in row["auto_exit_block_reason"]


def test_api_entry_price_is_verified_and_exit_eligible():
    module = _load()
    with tempfile.TemporaryDirectory() as tmp:
        tracker = module.PositionTracker(str(Path(tmp) / "positions.json"))
        assert tracker.sync_position_snapshot(
            symbol="AVAX-USD",
            quantity=0.3899519381,
            entry_price=22.50,
            current_price=24.00,
            size_usd=9.36,
            entry_price_source="api",
        )
        row = tracker.get_position("AVAX-USD")
        assert row["entry_price"] == 22.50
        assert row["entry_price_source"] == "api"
        assert row["cost_basis_verified"] is True
        assert row["auto_exit_blocked"] is False


def test_unverified_old_market_mark_is_not_promoted_by_later_snapshot():
    module = _load()
    with tempfile.TemporaryDirectory() as tmp:
        tracker = module.PositionTracker(str(Path(tmp) / "positions.json"))
        tracker.sync_position_snapshot(
            symbol="CELO-USD",
            quantity=35.34862,
            current_price=0.42,
            size_usd=14.85,
        )
        tracker.sync_position_snapshot(
            symbol="CELO-USD",
            quantity=35.34862,
            current_price=0.43,
            size_usd=15.20,
        )
        row = tracker.get_position("CELO-USD")
        assert row["cost_basis_verified"] is False
        assert row["entry_price_source"] == "estimated_from_adoption_mark"
        assert row["entry_price"] == 0.43


def test_entry_price_store_record_restores_verified_cost_basis():
    module = _load()

    class _Record:
        price = 132.75
        source = "api"
        quantity = 0.5

    class _Store:
        @staticmethod
        def get(symbol):
            assert symbol == "AAVE-USD"
            return _Record()

    with tempfile.TemporaryDirectory() as tmp:
        tracker = module.PositionTracker(str(Path(tmp) / "positions.json"))
        tracker._eps = _Store()
        assert tracker.sync_position_snapshot(
            symbol="AAVE-USD",
            quantity=0.5,
            entry_price=0.0,
            current_price=175.0,
            size_usd=87.5,
            entry_price_source="override",
        )
        row = tracker.get_position("AAVE-USD")
        assert row["entry_price"] == 132.75
        assert row["entry_price_source"] == "api"
        assert row["cost_basis_verified"] is True
        assert row["auto_exit_blocked"] is False


def test_entry_price_store_quantity_mismatch_keeps_position_unverified():
    module = _load()

    class _Record:
        price = 132.75
        source = "api"
        quantity = 9.0

    class _Store:
        @staticmethod
        def get(symbol):
            assert symbol == "AAVE-USD"
            return _Record()

    with tempfile.TemporaryDirectory() as tmp:
        tracker = module.PositionTracker(str(Path(tmp) / "positions.json"))
        tracker._eps = _Store()
        assert tracker.sync_position_snapshot(
            symbol="AAVE-USD",
            quantity=0.5,
            entry_price=0.0,
            current_price=175.0,
            size_usd=87.5,
            entry_price_source="override",
        )
        row = tracker.get_position("AAVE-USD")
        assert row["entry_price"] == 0.0
        assert row["entry_price_source"] == "reconciliation_required"
        assert row["cost_basis_verified"] is False
        assert row["auto_exit_blocked"] is True
