"""
Regression tests for CapitalAuthority.is_fresh() and is_brokers_complete().

Validates that snapshot-age freshness and broker completeness are evaluated
independently (fix for the LIVE_ACTIVE convergence regression where a
182-second-old snapshot was incorrectly rejected under a 240-second TTL
because broker completeness was bundled into is_fresh()).

Also validates that publish_snapshot() resets last_updated to the snapshot's
computed_at timestamp so subsequent refreshes evaluate freshness against the
current snapshot's age, not the previous one's (no age inheritance).
"""

from __future__ import annotations

import datetime
import threading
import unittest

import bot.capital_authority as ca_mod
from bot.capital_authority import CapitalAuthority


def _make_ca(
    broker_balances: dict | None = None,
    expected_brokers: int = 1,
    last_updated_age_s: float = 0.0,
    opportunistic: bool = False,
) -> CapitalAuthority:
    """Build a minimal CapitalAuthority instance for freshness tests."""
    ca_mod._EXPECTED_ID = None  # allow a fresh instance past the singleton guard

    ca = CapitalAuthority.__new__(CapitalAuthority)
    ca._lock = threading.RLock()
    ca._lock_timeout = 5.0
    ca._startup_lock = threading.Event()
    ca._startup_lock.set()
    ca.broker_manager = None
    ca._reserve_pct = 0.0
    ca._broker_balances = dict(broker_balances) if broker_balances else {}
    ca._broker_roles = {}
    ca._open_exposure_usd = 0.0
    ca._last_updated_total = sum(ca._broker_balances.values())
    ca._expected_brokers = expected_brokers
    ca._opportunistic = opportunistic
    ca._hydrated = bool(ca._broker_balances)
    ca._preserve_nonzero_ttl_s = 180.0
    ca._last_typed_snapshot = None
    ca._broker_feed_timestamps = {}
    ca._balance_feeds = {}
    ca._broker_registration_complete = threading.Event()
    ca._broker_registration_complete.set()
    ca._warm_start = False
    ca._pending_feeds = []

    if last_updated_age_s == 0.0:
        ca.last_updated = datetime.datetime.now(datetime.timezone.utc)
    else:
        ca.last_updated = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(seconds=last_updated_age_s)

    return ca


class TestIsFreshEvaluatesAgeOnly(unittest.TestCase):
    """is_fresh() must gate on snapshot age only, not broker completeness."""

    def test_fresh_snapshot_returns_true_regardless_of_broker_count(self):
        """182s-old snapshot under 240s TTL must pass even if expected_brokers=3 and only 1 present."""
        ca = _make_ca(
            broker_balances={"kraken": 468.14},
            expected_brokers=3,
            last_updated_age_s=182.0,
        )
        self.assertTrue(ca.is_fresh(ttl_s=240.0))

    def test_stale_snapshot_returns_false(self):
        """Snapshot older than the TTL must still fail."""
        ca = _make_ca(
            broker_balances={"kraken": 468.14},
            expected_brokers=1,
            last_updated_age_s=300.0,
        )
        self.assertFalse(ca.is_fresh(ttl_s=240.0))

    def test_no_snapshot_returns_false(self):
        """Never-refreshed authority (last_updated=None) must still fail."""
        ca = _make_ca()
        ca.last_updated = None
        self.assertFalse(ca.is_fresh(ttl_s=240.0))

    def test_fresh_snapshot_default_ttl(self):
        """A just-created snapshot passes the default (90s) TTL."""
        ca = _make_ca(broker_balances={"kraken": 100.0}, expected_brokers=1)
        self.assertTrue(ca.is_fresh())

    def test_zero_brokers_still_passes_if_snapshot_is_fresh(self):
        """is_fresh() must pass even when _broker_balances is empty — age only."""
        ca = _make_ca(broker_balances={}, expected_brokers=3, last_updated_age_s=5.0)
        self.assertTrue(ca.is_fresh(ttl_s=240.0))


class TestIsBrokersComplete(unittest.TestCase):
    """is_brokers_complete() is the separate broker-count gate."""

    def test_complete_when_all_expected_brokers_present(self):
        ca = _make_ca(
            broker_balances={"kraken": 150.0, "coinbase": 150.0, "okx": 168.14},
            expected_brokers=3,
        )
        self.assertTrue(ca.is_brokers_complete())

    def test_incomplete_when_fewer_than_expected(self):
        ca = _make_ca(
            broker_balances={"kraken": 468.14},
            expected_brokers=3,
        )
        self.assertFalse(ca.is_brokers_complete())

    def test_opportunistic_requires_only_one_broker(self):
        ca = _make_ca(
            broker_balances={"kraken": 468.14},
            expected_brokers=3,
            opportunistic=True,
        )
        self.assertTrue(ca.is_brokers_complete())

    def test_empty_balances_returns_false(self):
        ca = _make_ca(broker_balances={}, expected_brokers=1)
        self.assertFalse(ca.is_brokers_complete())


class TestFreshnessAndCompletenessSeparated(unittest.TestCase):
    """Confirms the two gates can disagree — their independence is the fix."""

    def test_fresh_but_incomplete(self):
        """Snapshot is recent but not all brokers have reported — fresh=True, complete=False."""
        ca = _make_ca(
            broker_balances={"kraken": 468.14},
            expected_brokers=3,
            last_updated_age_s=182.0,
        )
        self.assertTrue(ca.is_fresh(ttl_s=240.0))
        self.assertFalse(ca.is_brokers_complete())

    def test_complete_but_stale(self):
        """All brokers reported but snapshot is too old — fresh=False, complete=True."""
        ca = _make_ca(
            broker_balances={"k": 100.0, "c": 100.0, "o": 100.0},
            expected_brokers=3,
            last_updated_age_s=300.0,
        )
        self.assertFalse(ca.is_fresh(ttl_s=240.0))
        self.assertTrue(ca.is_brokers_complete())


class _FakeSnapshot:
    """Minimal duck-typed snapshot accepted by publish_snapshot()."""

    def __init__(self, broker_balances: dict, computed_at: datetime.datetime) -> None:
        self.broker_balances = broker_balances
        self.computed_at = computed_at
        self.open_exposure_usd = 0.0
        self.real_capital = float(sum(broker_balances.values()))
        self.broker_count = len(broker_balances)


class TestPublishSnapshotResetsLastUpdated(unittest.TestCase):
    """publish_snapshot() must stamp last_updated with the snapshot's computed_at.

    This is the regression guard for the 'age inheritance' bug: a warm-start
    authority loads last_updated from the disk cache (possibly hours old).
    After publish_snapshot() accepts the first live snapshot, last_updated must
    reflect the snapshot's computed_at — NOT the cached timestamp — so
    is_fresh() and is_stale() evaluate the correct (current) age.
    """

    def _make_fresh_ca_for_publish(self) -> CapitalAuthority:
        """Create a CA instance that can accept publish_snapshot() calls."""
        ca_mod._EXPECTED_ID = None
        ca = CapitalAuthority.__new__(CapitalAuthority)
        ca._lock = threading.RLock()
        ca._lock_timeout = 5.0
        ca._startup_lock = threading.Event()
        ca._startup_lock.set()
        ca.broker_manager = None
        ca._reserve_pct = 0.0
        ca._broker_balances = {}
        ca._broker_roles = {}
        ca._open_exposure_usd = 0.0
        ca._last_updated_total = 0.0
        ca._expected_brokers = 1
        ca._opportunistic = True
        ca._hydrated = False
        ca._first_snap_accepted = False
        ca._preserve_nonzero_ttl_s = 180.0
        ca._last_typed_snapshot = None
        ca._broker_feed_timestamps = {}
        ca._balance_feeds = {}
        ca._broker_registration_complete = threading.Event()
        ca._broker_registration_complete.set()
        ca._warm_start = False
        ca._pending_feeds = []
        ca.last_updated = None
        ca_mod._EXPECTED_ID = id(ca)
        return ca

    def test_publish_snapshot_replaces_stale_last_updated(self):
        """After a successful publish_snapshot(), last_updated equals computed_at.

        Scenario: authority warm-started with an hours-old cache timestamp.
        A fresh snapshot arrives; last_updated must advance to computed_at so
        is_fresh() returns True for the new snapshot's age (not the cache age).
        """
        ca = self._make_fresh_ca_for_publish()

        old_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
        ca.last_updated = old_ts

        computed_at = datetime.datetime.now(datetime.timezone.utc)
        snap = _FakeSnapshot({"coinbase": 250.0}, computed_at)

        accepted = ca.publish_snapshot(snap, writer_id="mabm_capital_refresh_coordinator")

        self.assertTrue(accepted, "publish_snapshot should accept a snapshot newer than cached timestamp")
        self.assertEqual(ca.last_updated, computed_at,
                         "last_updated must be set to computed_at, not the old cached value")
        self.assertTrue(ca.is_fresh(),
                        "is_fresh() must return True immediately after accepting a current snapshot")
        self.assertFalse(ca.is_stale(),
                         "is_stale() must return False immediately after accepting a current snapshot")

    def test_second_publish_does_not_inherit_first_snapshot_age(self):
        """Two successive publish_snapshot() calls each stamp their own computed_at.

        Validates that the second snapshot does not inherit the first snapshot's
        computed_at: last_updated advances to the second snapshot's timestamp.
        """
        ca = self._make_fresh_ca_for_publish()

        t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=30)
        snap1 = _FakeSnapshot({"coinbase": 200.0}, t1)
        ca.publish_snapshot(snap1, writer_id="mabm_capital_refresh_coordinator")
        self.assertEqual(ca.last_updated, t1)

        t2 = datetime.datetime.now(datetime.timezone.utc)
        snap2 = _FakeSnapshot({"coinbase": 210.0}, t2)
        accepted2 = ca.publish_snapshot(snap2, writer_id="mabm_capital_refresh_coordinator")

        self.assertTrue(accepted2)
        self.assertEqual(ca.last_updated, t2,
                         "last_updated must advance to t2, not remain at t1 (no age inheritance)")
        self.assertTrue(ca.is_fresh())

    def test_stale_warm_start_becomes_fresh_after_publish(self):
        """An authority loaded from hours-old cache reports stale until publish_snapshot.

        This directly exercises the startup-freshness timing fix: before the fix,
        callers could not distinguish between 'not yet refreshed' and
        'refreshed but age-stale'; now is_fresh() correctly reflects the
        current snapshot age after publish.
        """
        ca = self._make_fresh_ca_for_publish()
        old_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        ca.last_updated = old_ts
        ca._broker_balances = {"coinbase": 468.14}
        ca._hydrated = True

        self.assertFalse(ca.is_fresh(ttl_s=90.0),
                         "warm-start authority must initially report not-fresh")
        self.assertTrue(ca.is_stale(ttl_s=90.0),
                        "warm-start authority must initially report stale")

        computed_at = datetime.datetime.now(datetime.timezone.utc)
        snap = _FakeSnapshot({"coinbase": 468.14}, computed_at)
        ca.publish_snapshot(snap, writer_id="mabm_capital_refresh_coordinator")

        self.assertTrue(ca.is_fresh(ttl_s=90.0),
                        "authority must be fresh immediately after accepting a current snapshot")
        self.assertFalse(ca.is_stale(ttl_s=90.0),
                         "authority must not be stale after accepting a current snapshot")


if __name__ == "__main__":
    unittest.main()
