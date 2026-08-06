from __future__ import annotations

import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import bot.capital_authority as ca_mod
from bot.capital_authority import CapitalAuthority, SnapshotPublicationStatus
from bot.capital_csm_v2 import CapitalCSMv2, CapitalCSMState
from bot.capital_flow_state_machine import (
    CapitalBootstrapState,
    CapitalEventBus,
    CapitalEventType,
    CapitalRefreshCoordinator,
    CapitalRuntimeStateMachine,
    get_capital_bootstrap_fsm,
)


class _AuthorityForCSM:
    def __init__(self, status: SnapshotPublicationStatus) -> None:
        self._broker_registration_complete = threading.Event()
        self._broker_registration_complete.set()
        self.is_hydrated = True
        self._status = status

    def get_snapshot_publication_status(self) -> SnapshotPublicationStatus:
        return self._status


class _AuthorityForCoordinator:
    def __init__(self, status: SnapshotPublicationStatus) -> None:
        self.reserve_pct = 0.1
        self.expected_brokers = 1
        self.opportunistic = False
        self.last_updated = datetime.now(timezone.utc)
        self._status = status
        self.publish_calls = 0

    def get_raw_per_broker(self, _broker_key: str) -> float:
        return 0.0

    def publish_snapshot(self, _snapshot, writer_id: str) -> bool:
        _ = writer_id
        self.publish_calls += 1
        return True

    def get_snapshot_publication_status(self) -> SnapshotPublicationStatus:
        return self._status


class _PositiveBroker:
    def __init__(self, balance: float) -> None:
        self._balance = balance
        self._fetched_at = datetime.now(timezone.utc).timestamp()

    def get_account_balance(self):
        return self._balance

    def get_balance_fetch_timestamp(self):
        return self._fetched_at

    def get_last_pricing_coverage(self):
        return 1.0

    def get_error_count(self):
        return 0


class _FakeSnapshot:
    def __init__(self, broker_balances: dict[str, float], computed_at: datetime) -> None:
        self.broker_balances = broker_balances
        self.computed_at = computed_at
        self.open_exposure_usd = 0.0
        self.real_capital = float(sum(broker_balances.values()))
        self.broker_count = len(broker_balances)


def _make_bare_ca() -> CapitalAuthority:
    ca_mod._EXPECTED_ID = None
    ca = CapitalAuthority.__new__(CapitalAuthority)
    ca._lock = threading.RLock()
    ca.broker_manager = None
    ca._reserve_pct = 0.0
    ca._broker_balances = {}
    ca._broker_roles = {}
    ca._open_exposure_usd = 0.0
    ca._last_updated_total = 0.0
    ca.last_updated = None
    ca._expected_brokers = 1
    ca._opportunistic = True
    ca._preserve_nonzero_ttl_s = 180.0
    ca._last_typed_snapshot = None
    ca._hydrated = False
    ca._first_snap_accepted = False
    ca._last_snapshot_publication = SnapshotPublicationStatus(
        accepted=False,
        stale=True,
        reason="init",
        timestamp=None,
        expiry=None,
    )
    ca._broker_feed_timestamps = {}
    ca._balance_feeds = {}
    ca._broker_registration_complete = threading.Event()
    ca._broker_registration_complete.set()
    ca._startup_lock = threading.Event()
    ca._startup_lock.set()
    ca._pending_feeds = []
    ca._warm_start = False
    ca._AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"
    ca_mod._EXPECTED_ID = id(ca)
    return ca


class CapitalSnapshotPublicationStatusTests(unittest.TestCase):
    def test_accepted_snapshot_remains_accepted_downstream(self) -> None:
        status = SnapshotPublicationStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=datetime.now(timezone.utc),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        fake_ca = _AuthorityForCSM(status)
        snapshot = SimpleNamespace(
            real_capital=125.0,
            broker_count=1,
            computed_at=datetime.now(timezone.utc),
            confidence=SimpleNamespace(confidence_score=0.9),
            is_stale=True,  # contradictory source field; CSM must trust CA status
        )
        csm = CapitalCSMv2()
        with patch.dict(os.environ, {"LIVE_CAPITAL_VERIFIED": "true"}, clear=False), patch(
            "bot.capital_authority.get_capital_authority",
            return_value=fake_ca,
        ):
            state = csm.ingest_snapshot(snapshot)
        self.assertEqual(state, CapitalCSMState.READY)
        self.assertTrue(csm.first_snap_accepted)

    def test_stale_snapshot_triggers_refresh_only(self) -> None:
        stale_status = SnapshotPublicationStatus(
            accepted=False,
            stale=True,
            reason="snapshot expired at publish",
            timestamp=datetime.now(timezone.utc),
            expiry=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        authority = _AuthorityForCoordinator(stale_status)
        bootstrap = get_capital_bootstrap_fsm()
        bootstrap.claim_bootstrap_ownership()
        bootstrap.force_transition(CapitalBootstrapState.BOOT_IDLE, "test reset")
        bus_events = []
        bus = CapitalEventBus()
        coordinator = CapitalRefreshCoordinator(
            event_bus=bus,
            runtime_fsm=CapitalRuntimeStateMachine(),
            bootstrap_fsm=bootstrap,
        )
        bus.subscribe(lambda event: bus_events.append(event.event_type))
        with patch(
            "bot.capital_authority.get_capital_authority",
            return_value=authority,
        ):
            snapshot = coordinator.execute_refresh(
                broker_map={"kraken": _PositiveBroker(100.0)},
                trigger="watchdog",
                open_exposure_usd=0.0,
            )
        bus.dispatch_pending()
        self.assertIsNone(snapshot)
        self.assertIn(CapitalEventType.REFRESH_REQUESTED, bus_events)

    def test_watchdog_does_not_republish_stale_snapshot(self) -> None:
        stale_status = SnapshotPublicationStatus(
            accepted=False,
            stale=True,
            reason="snapshot expired at publish",
            timestamp=datetime.now(timezone.utc),
            expiry=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        authority = _AuthorityForCoordinator(stale_status)
        bootstrap = get_capital_bootstrap_fsm()
        bootstrap.claim_bootstrap_ownership()
        bootstrap.force_transition(CapitalBootstrapState.BOOT_IDLE, "test reset")
        bus_events = []
        bus = CapitalEventBus()
        coordinator = CapitalRefreshCoordinator(
            event_bus=bus,
            runtime_fsm=CapitalRuntimeStateMachine(),
            bootstrap_fsm=bootstrap,
        )
        bus.subscribe(lambda event: bus_events.append(event.event_type))
        with patch(
            "bot.capital_authority.get_capital_authority",
            return_value=authority,
        ):
            coordinator.execute_refresh(
                broker_map={"kraken": _PositiveBroker(100.0)},
                trigger="watchdog",
                open_exposure_usd=0.0,
            )
        bus.dispatch_pending()
        self.assertNotIn(CapitalEventType.SNAPSHOT_PUBLISHED, bus_events)
        self.assertEqual(authority.publish_calls, 1)

    def test_cache_timestamps_updated_on_publish(self) -> None:
        ca = _make_bare_ca()
        t1 = datetime.now(timezone.utc) - timedelta(seconds=10)
        t2 = datetime.now(timezone.utc)
        s1 = _FakeSnapshot({"kraken": 90.0}, t1)
        s2 = _FakeSnapshot({"kraken": 95.0}, t2)
        self.assertTrue(ca.publish_snapshot(s1, writer_id="mabm_capital_refresh_coordinator"))
        self.assertTrue(ca.publish_snapshot(s2, writer_id="mabm_capital_refresh_coordinator"))
        self.assertEqual(ca._broker_feed_timestamps["kraken"], t2)

    def test_no_accepted_true_and_stale_true_contradiction(self) -> None:
        ca = _make_bare_ca()
        stale_computed_at = datetime.now(timezone.utc) - timedelta(seconds=300)
        stale_snapshot = _FakeSnapshot({"kraken": 50.0}, stale_computed_at)
        self.assertTrue(ca.publish_snapshot(stale_snapshot, writer_id="mabm_capital_refresh_coordinator"))
        status = ca.get_snapshot_publication_status()
        self.assertFalse(status.accepted)
        self.assertTrue(status.stale)
        self.assertFalse(status.accepted and status.stale)


if __name__ == "__main__":
    unittest.main()
