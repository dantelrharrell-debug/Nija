from __future__ import annotations

import time
from types import SimpleNamespace


def _broker(*, connected=True, snapshot=False, tracker_rows=0):
    class Tracker:
        def get_all_positions(self):
            return [f"SYM{i}" for i in range(tracker_rows)]

    broker = SimpleNamespace(
        connected=connected,
        position_tracker=Tracker(),
    )
    if snapshot:
        broker._nija_authoritative_position_snapshot_at_monotonic_v285 = time.monotonic()
        broker._nija_authoritative_position_snapshot_rows_v285 = (
            {"symbol": "ETH-USD", "quantity": 1.0},
        )
    return broker


def test_fresh_v285_object_ranks_above_connected_prebootstrap_object():
    from bot import runtime_universal_exit_broker_rebinding_v331_patch as v331

    old = _broker(connected=True, snapshot=False, tracker_rows=0)
    canonical = _broker(connected=True, snapshot=True, tracker_rows=1)

    assert v331._rank(canonical) > v331._rank(old)


def test_equal_evidence_does_not_force_rebinding():
    from bot import runtime_universal_exit_broker_rebinding_v331_patch as v331

    first = _broker(connected=True, snapshot=False, tracker_rows=0)
    duplicate = _broker(connected=True, snapshot=False, tracker_rows=0)

    assert v331._rank(first) == v331._rank(duplicate)


def test_tracker_positions_rank_above_empty_disconnected_object():
    from bot import runtime_universal_exit_broker_rebinding_v331_patch as v331

    stale = _broker(connected=False, snapshot=False, tracker_rows=0)
    live = _broker(connected=True, snapshot=False, tracker_rows=2)

    assert v331._rank(live) > v331._rank(stale)
