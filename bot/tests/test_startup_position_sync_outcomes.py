from __future__ import annotations

import logging
from types import SimpleNamespace

from bot import startup_position_sync


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
