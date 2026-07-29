"""
Regression tests for CapitalAuthority.is_fresh() and is_brokers_complete().

Validates that snapshot-age freshness and broker completeness are evaluated
independently (fix for the LIVE_ACTIVE convergence regression where a
182-second-old snapshot was incorrectly rejected under a 240-second TTL
because broker completeness was bundled into is_fresh()).
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


if __name__ == "__main__":
    unittest.main()
