from __future__ import annotations

from bot.position_adoption_exit_integrity_patch import install_import_hook
from bot.position_tracker import PositionTracker


def test_broker_existing_adoption_replaces_quantity_instead_of_adding(tmp_path):
    install_import_hook()
    tracker = PositionTracker(storage_file=str(tmp_path / "positions.json"))

    assert tracker.track_entry(
        symbol="SOL-USD",
        entry_price=81.99,
        quantity=0.51389914,
        size_usd=42.13,
        strategy="APEX_v7.1",
        position_source="nija_strategy",
    )

    assert tracker.track_entry(
        symbol="SOL-USD",
        entry_price=81.99,
        quantity=0.51389914,
        size_usd=39.19,
        strategy="POSITION_ADOPTION",
        position_source="broker_existing",
    )

    position = tracker.get_position("SOL-USD")
    assert position is not None
    assert position["quantity"] == 0.51389914
    assert position["entry_price"] == 81.99
    assert position["cost_basis_verified"] is True
    assert position["auto_exit_blocked"] is False


def test_unverified_snapshot_preserves_existing_verified_cost_basis(tmp_path):
    install_import_hook()
    tracker = PositionTracker(storage_file=str(tmp_path / "positions.json"))

    assert tracker.track_entry(
        symbol="ETH-USD",
        entry_price=1785.89673974,
        quantity=0.03810679,
        size_usd=68.05,
        strategy="APEX_v7.1",
        position_source="nija_strategy",
    )

    assert tracker.track_entry(
        symbol="ETH-USD",
        entry_price=0.0,
        quantity=0.03810679,
        size_usd=71.72,
        strategy="POSITION_ADOPTION",
        position_source="broker_existing",
    )

    position = tracker.get_position("ETH-USD")
    assert position is not None
    assert position["quantity"] == 0.03810679
    assert position["entry_price"] == 1785.89673974
    assert position["cost_basis_verified"] is True
    assert position["auto_exit_blocked"] is False
