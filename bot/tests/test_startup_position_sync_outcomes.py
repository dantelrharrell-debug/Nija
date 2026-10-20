from __future__ import annotations

import logging
from types import SimpleNamespace

from bot import startup_position_sync
from bot import position_tracker


class PositionTracker:
    def __init__(self) -> None:
        self.positions = [{"symbol": "ETH-USD", "quantity": 0.5}]

    def get_all_positions(self):
        return self.positions


def _result_log(caplog, classification: str) -> str:
    return next(
        record.getMessage()
        for record in caplog.records
        if "EXCHANGE_POSITION_SYNC_RESULT" in record.getMessage()
        and f"classification={classification}" in record.getMessage()
    )


def test_fetch_failure_is_timestamped_and_does_not_change_positions(caplog):
    tracker = PositionTracker()

    def fail_fetch():
        raise TimeoutError("snapshot timeout")

    broker = SimpleNamespace(position_tracker=tracker, get_positions=fail_fetch)
    caplog.set_level(logging.INFO, logger="nija")

    assert startup_position_sync._adopt_broker_positions(broker, "platform:kraken", None) == 0

    result = _result_log(caplog, "fetch_failed")
    assert "source=broker.get_positions" in result
    assert "observed_at_epoch=" in result
    assert "error_type=TimeoutError" in result
    assert tracker.positions == [{"symbol": "ETH-USD", "quantity": 0.5}]
    assert broker._startup_position_sync_adopted is False


def test_partial_snapshot_is_classified_without_mutating_tracker(caplog):
    tracker = PositionTracker()
    broker = SimpleNamespace(
        position_tracker=tracker,
        get_positions=lambda: [{"symbol": "", "quantity": 1}],
    )
    caplog.set_level(logging.INFO, logger="nija")

    assert startup_position_sync._adopt_broker_positions(broker, "platform:kraken", None) == 0

    result = _result_log(caplog, "reconciliation_failed")
    assert "source=broker.get_positions" in result
    assert "fetched=1" in result
    assert "resolved=0" in result
    assert tracker.positions == [{"symbol": "ETH-USD", "quantity": 0.5}]
    assert broker._startup_position_sync_adopted is False


def test_explicit_empty_snapshot_is_distinguished_from_fetch_failure(caplog):
    tracker = PositionTracker()
    broker = SimpleNamespace(position_tracker=tracker, get_positions=lambda: [])
    caplog.set_level(logging.INFO, logger="nija")

    assert startup_position_sync._adopt_broker_positions(broker, "platform:kraken", None) == 0

    result = _result_log(caplog, "synchronized_empty")
    assert "source=broker.get_positions" in result
    assert "fetched=0" in result
    assert "resolved=0" in result
    assert tracker.positions == [{"symbol": "ETH-USD", "quantity": 0.5}]
    assert broker._startup_position_sync_adopted is True


def test_baby_unknown_basis_survives_intermittent_sync_and_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(position_tracker, "ENTRY_PRICE_STORE_AVAILABLE", False)
    monkeypatch.setattr(position_tracker, "DustPositionManager", None)
    path = tmp_path / "positions.json"
    tracker = position_tracker.PositionTracker(str(path))
    snapshot = [{"symbol": "BABY-USD", "quantity": 0.00142, "current_price": 0.0}]
    broker = SimpleNamespace(position_tracker=tracker, get_positions=lambda: snapshot)

    for attempt in range(3):
        if attempt == 1:
            def fail_fetch():
                raise TimeoutError("snapshot timeout")
            broker.get_positions = fail_fetch
        else:
            broker.get_positions = lambda: snapshot
        startup_position_sync._adopt_broker_positions(broker, "platform:kraken", None)
        row = tracker.get_position("BABY-USD")
        assert row["quantity"] == 0.00142
        assert row["entry_price"] == 0.0
        assert row["entry_price_source"] == "reconciliation_required"
        assert row["cost_basis_verified"] is False
        assert row["auto_exit_blocked"] is True
        assert broker._startup_position_sync_adopted is False

    reloaded = position_tracker.PositionTracker(str(path))
    assert reloaded.get_position("BABY-USD") == tracker.get_position("BABY-USD")


def test_verified_basis_is_not_erased_by_intermittent_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(position_tracker, "ENTRY_PRICE_STORE_AVAILABLE", False)
    monkeypatch.setattr(position_tracker, "DustPositionManager", None)
    tracker = position_tracker.PositionTracker(str(tmp_path / "positions.json"))
    snapshot = [{"symbol": "BABY-USD", "quantity": 0.00142}]
    broker = SimpleNamespace(
        position_tracker=tracker, get_positions=lambda: snapshot,
        get_real_entry_price=lambda symbol: 0.035,
    )
    startup_position_sync._adopt_broker_positions(broker, "platform:kraken", None)
    before = tracker.get_position("BABY-USD")
    assert before["cost_basis_verified"] is True
    assert broker._startup_position_sync_adopted is True

    def fail_fetch():
        raise TimeoutError("snapshot timeout")

    broker.get_positions = fail_fetch
    startup_position_sync._adopt_broker_positions(broker, "platform:kraken", None)
    assert broker._startup_position_sync_adopted is False
    assert tracker.get_position("BABY-USD") == before

    broker.get_positions = lambda: snapshot
    broker.get_real_entry_price = lambda symbol: 0.0
    startup_position_sync._adopt_broker_positions(broker, "platform:kraken", None)
    after = tracker.get_position("BABY-USD")
    assert after["quantity"] == before["quantity"]
    assert after["entry_price"] == before["entry_price"]
    assert after["cost_basis_verified"] is True
    assert broker._startup_position_sync_adopted is True


def test_position_tracker_rejects_nonfinite_broker_values(monkeypatch, tmp_path):
    """Malformed numeric evidence cannot become real positions, basis, or marks."""
    monkeypatch.setattr(position_tracker, "ENTRY_PRICE_STORE_AVAILABLE", False)
    monkeypatch.setattr(position_tracker, "DustPositionManager", None)
    path = tmp_path / "positions.json"
    tracker = position_tracker.PositionTracker(str(path))

    for invalid in (float("inf"), float("-inf"), float("nan"),
                    "inf", "-Infinity", "NaN"):
        assert tracker._safe_float(invalid) == 0.0

    assert tracker.sync_position_snapshot(
        "BABY-USD", 0.00142,
        entry_price=float("inf"),
        current_price=float("-inf"),
        size_usd=float("nan"),
        entry_price_source="trade_history",
    )
    before = tracker.get_position("BABY-USD")
    assert before["quantity"] == 0.00142
    assert before["entry_price"] == 0.0
    assert before["cost_basis_verified"] is False
    assert before["auto_exit_blocked"] is True
    assert before["last_broker_snapshot_price"] == 0.0
    assert before["last_broker_snapshot_value_usd"] == 0.0

    for invalid_quantity in (float("inf"), float("-inf"), float("nan")):
        assert not tracker.sync_position_snapshot(
            "BABY-USD", invalid_quantity,
            entry_price=0.5, entry_price_source="trade_history",
        )
        assert tracker.get_position("BABY-USD") == before

    persisted = path.read_text(encoding="utf-8")
    assert "NaN" not in persisted
    assert "Infinity" not in persisted


def test_nonfinite_snapshot_mark_cannot_erase_verified_entry(monkeypatch, tmp_path):
    """Invalid marks are not evidence of an entry or a changed cost basis."""
    monkeypatch.setattr(position_tracker, "ENTRY_PRICE_STORE_AVAILABLE", False)
    monkeypatch.setattr(position_tracker, "DustPositionManager", None)
    tracker = position_tracker.PositionTracker(str(tmp_path / "positions.json"))
    assert tracker.sync_position_snapshot(
        "BTC-USD", 0.5, entry_price=35000.0,
        entry_price_source="trade_history",
    )
    before = tracker.get_position("BTC-USD")
    assert before["cost_basis_verified"] is True

    assert tracker.sync_position_snapshot(
        "BTC-USD", 0.5,
        entry_price=float("inf"),
        current_price=float("nan"),
        size_usd=float("inf"),
        entry_price_source="trade_history",
    )
    after = tracker.get_position("BTC-USD")
    assert after["entry_price"] == before["entry_price"] == 35000.0
    assert after["quantity"] == before["quantity"] == 0.5
    assert after["cost_basis_verified"] is True
    assert after["last_broker_snapshot_price"] == 0.0
    assert after["last_broker_snapshot_value_usd"] == 0.0


def test_invalid_entry_price_store_quantity_cannot_verify_basis(monkeypatch, tmp_path):
    """Untrusted stored quantities cannot become 'unknown quantity' wildcards.

    Keep EntryPriceStore enabled: the original tests disabled the fallback
    containing the invalid-quantity verification bypass.
    """
    from bot.entry_price_store import EntryPriceStore

    monkeypatch.setattr(position_tracker, "ENTRY_PRICE_STORE_AVAILABLE", True)
    monkeypatch.setattr(position_tracker, "DustPositionManager", None)
    store = EntryPriceStore(str(tmp_path / "entry_prices.json"))
    monkeypatch.setattr(position_tracker, "get_entry_price_store", lambda: store)
    tracker = position_tracker.PositionTracker(str(tmp_path / "positions.json"))

    for bad_qty in (float("inf"), float("-inf"), float("nan"), -1.0):
        store.save("BABY-USD", 0.035, source="api", quantity=bad_qty)
        assert tracker.sync_position_snapshot("BABY-USD", 0.00142)
        row = tracker.get_position("BABY-USD")
        assert row["quantity"] == 0.00142
        assert row["entry_price"] == 0.0
        assert row["entry_price_source"] == "reconciliation_required"
        assert row["cost_basis_verified"] is False
        assert row["auto_exit_blocked"] is True

    # A correctly scoped stored quantity remains eligible for verified reuse.
    store.save("BABY-USD", 0.035, source="api", quantity=0.00142)
    assert tracker.sync_position_snapshot("BABY-USD", 0.00142)
    verified = tracker.get_position("BABY-USD")
    assert verified["entry_price"] == 0.035
    assert verified["cost_basis_verified"] is True
    assert verified["auto_exit_blocked"] is False


def test_legacy_zero_store_quantity_keeps_explicit_compatibility(monkeypatch, tmp_path):
    """Preserve historical quantity=0 matching, but never for malformed data."""
    from bot.entry_price_store import EntryPriceStore

    monkeypatch.setattr(position_tracker, "ENTRY_PRICE_STORE_AVAILABLE", True)
    monkeypatch.setattr(position_tracker, "DustPositionManager", None)
    store = EntryPriceStore(str(tmp_path / "entry_prices.json"))
    monkeypatch.setattr(position_tracker, "get_entry_price_store", lambda: store)
    store.save("BTC-USD", 20000.0, source="trade_history", quantity=0.0)
    tracker = position_tracker.PositionTracker(str(tmp_path / "positions.json"))

    assert tracker.sync_position_snapshot("BTC-USD", 0.001)
    row = tracker.get_position("BTC-USD")
    assert row["entry_price"] == 20000.0
    assert row["cost_basis_verified"] is True
