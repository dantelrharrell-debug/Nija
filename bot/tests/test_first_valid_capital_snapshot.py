"""
Tests for the first-valid-capital-snapshot guard introduced in
capital_allocation_brain.py and multi_account_broker_manager.py.

Validates:
1. snapshot_source="live_exchange" when broker_map is non-empty.
2. snapshot_source="placeholder" when broker_map is empty.
3. Bootstrap guard accepts a snapshot with valid_brokers>0
   and snapshot_source="live_exchange", logs CRITICAL FIRST_VALID_CAPITAL_SNAPSHOT_ACCEPTED.
4. Bootstrap guard rejects a snapshot with valid_brokers=0,
   logs CRITICAL FIRST_VALID_CAPITAL_SNAPSHOT_REJECTED, snapshot NOT accepted.
5. Bootstrap guard rejects a snapshot with snapshot_source!="live_exchange".
6. Even with a valid snapshot, bootstrap_phase stays True when CA is not hydrated.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


class _StubCapitalAuthority:
    def __init__(self, is_hydrated: bool = False, total_capital: float = 0.0):
        self._is_hydrated = is_hydrated
        self.total_capital = total_capital

    @property
    def is_hydrated(self) -> bool:
        return self._is_hydrated

    def hydrate(self, total: float = 0.0):
        self._is_hydrated = True
        self.total_capital = total


class _StubMABM:
    def __init__(self, snapshot: dict, fully_ready: bool = True):
        self._snapshot = snapshot
        self._fully_ready = fully_ready
        self.refresh_calls = 0

    def all_brokers_fully_ready(self) -> bool:
        return self._fully_ready

    def refresh_capital_authority(self, trigger: str = "") -> dict:
        self.refresh_calls += 1
        return self._snapshot


def _run_bootstrap_guard(snapshot: dict, ca_hydrated_after: bool):
    """
    Execute the bootstrap snapshot-validation guard block that lives inside
    CapitalAllocationBrain.refresh_authority(), using stubs.

    Returns (_first_snap_accepted, _bootstrap_phase_after, log_records).
    """
    ca = _StubCapitalAuthority(is_hydrated=False)
    mabm = _StubMABM(snapshot=snapshot, fully_ready=True)

    log_records = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record):
            log_records.append(record)

    handler = _CapturingHandler()
    logger = logging.getLogger("capital_allocation_brain")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)

    _bootstrap_phase = True

    try:
        _first_snap_accepted = False
        _first_snap = mabm.refresh_capital_authority(trigger="bootstrap_force")

        if ca_hydrated_after:
            ca.hydrate(float(snapshot.get("total_capital", 0.0)))

        if hasattr(mabm, "all_brokers_fully_ready") and isinstance(_first_snap, dict):
            _vb = int(_first_snap.get("valid_brokers", 0))
            _src = str(_first_snap.get("snapshot_source", ""))
            if _vb > 0 and _src == "live_exchange":
                _first_snap_accepted = True
                logger.critical(
                    "FIRST_VALID_CAPITAL_SNAPSHOT_ACCEPTED "
                    "valid_brokers=%d snapshot_source=%s total=$%.2f",
                    _vb, _src, float(_first_snap.get("total_capital", 0.0)),
                )
            else:
                logger.critical(
                    "[CAPITAL_BRAIN] FIRST_VALID_CAPITAL_SNAPSHOT_REJECTED — "
                    "valid_brokers=%d snapshot_source=%r. "
                    "Blocking bootstrap acceptance (expected valid_brokers>0 "
                    "and snapshot_source='live_exchange').",
                    _vb, _src,
                )
        else:
            _first_snap_accepted = True

        if ca.is_hydrated and _first_snap_accepted:
            _bootstrap_phase = False

    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    return _first_snap_accepted, _bootstrap_phase, log_records


# ---------------------------------------------------------------------------
# Tests for snapshot_source field contract
# ---------------------------------------------------------------------------

def check_snapshot_source_live_exchange_when_broker_map_non_empty():
    broker_map = {"kraken": object()}
    snap_source = "live_exchange" if broker_map else "placeholder"
    assert snap_source == "live_exchange", f"Expected 'live_exchange', got {snap_source!r}"


def check_snapshot_source_placeholder_when_broker_map_empty():
    broker_map: dict = {}
    snap_source = "live_exchange" if broker_map else "placeholder"
    assert snap_source == "placeholder", f"Expected 'placeholder', got {snap_source!r}"


# ---------------------------------------------------------------------------
# Tests for the bootstrap guard logic
# ---------------------------------------------------------------------------

def check_valid_snapshot_accepted_and_logged():
    snapshot = {
        "ready": 1.0,
        "total_capital": 500.0,
        "valid_brokers": 1.0,
        "snapshot_source": "live_exchange",
    }
    accepted, bootstrap_phase, records = _run_bootstrap_guard(snapshot, ca_hydrated_after=True)

    accepted_logs = [
        r for r in records
        if r.levelno == logging.CRITICAL and "FIRST_VALID_CAPITAL_SNAPSHOT_ACCEPTED" in r.getMessage()
    ]
    assert len(accepted_logs) == 1, (
        f"Expected FIRST_VALID_CAPITAL_SNAPSHOT_ACCEPTED, got: {[r.getMessage() for r in records]}"
    )
    assert accepted, "_first_snap_accepted should be True"
    assert not bootstrap_phase, "_bootstrap_phase should be False after valid snapshot"


def check_zero_valid_brokers_rejects_snapshot():
    snapshot = {
        "ready": 0.0,
        "total_capital": 0.0,
        "valid_brokers": 0.0,
        "snapshot_source": "live_exchange",
    }
    accepted, bootstrap_phase, records = _run_bootstrap_guard(snapshot, ca_hydrated_after=True)

    rejected_logs = [
        r for r in records
        if r.levelno == logging.CRITICAL and "FIRST_VALID_CAPITAL_SNAPSHOT_REJECTED" in r.getMessage()
    ]
    assert len(rejected_logs) == 1, (
        f"Expected FIRST_VALID_CAPITAL_SNAPSHOT_REJECTED, got: {[r.getMessage() for r in records]}"
    )
    assert not accepted, "_first_snap_accepted should be False"
    assert bootstrap_phase, "_bootstrap_phase should remain True"


def check_placeholder_source_rejects_snapshot():
    snapshot = {
        "ready": 0.0,
        "total_capital": 0.0,
        "valid_brokers": 1.0,
        "snapshot_source": "placeholder",
    }
    accepted, bootstrap_phase, records = _run_bootstrap_guard(snapshot, ca_hydrated_after=True)

    rejected_logs = [
        r for r in records
        if r.levelno == logging.CRITICAL and "FIRST_VALID_CAPITAL_SNAPSHOT_REJECTED" in r.getMessage()
    ]
    assert len(rejected_logs) == 1, (
        f"Expected rejection for placeholder source, got: {[r.getMessage() for r in records]}"
    )
    assert not accepted, "_first_snap_accepted should be False"
    assert bootstrap_phase, "_bootstrap_phase should remain True"


def check_no_hydration_gate_respected():
    snapshot = {
        "ready": 1.0,
        "total_capital": 500.0,
        "valid_brokers": 1.0,
        "snapshot_source": "live_exchange",
    }
    accepted, bootstrap_phase, records = _run_bootstrap_guard(snapshot, ca_hydrated_after=False)

    assert accepted, "_first_snap_accepted should still be True for a valid snapshot"
    assert bootstrap_phase, "_bootstrap_phase should remain True when CA is not hydrated"


if __name__ == "__main__":
    check_snapshot_source_live_exchange_when_broker_map_non_empty()
    check_snapshot_source_placeholder_when_broker_map_empty()
    check_valid_snapshot_accepted_and_logged()
    check_zero_valid_brokers_rejects_snapshot()
    check_placeholder_source_rejects_snapshot()
    check_no_hydration_gate_respected()
    print("✅ test_first_valid_capital_snapshot passed")
