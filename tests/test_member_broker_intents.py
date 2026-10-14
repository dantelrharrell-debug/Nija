"""Tests durable order intent replay protection without broker calls."""
import os
import tempfile
import unittest

from bot.member_broker_cells import CellKey
from bot.member_broker_leases import AccountLeaseStore
from bot.member_broker_intents import IntentStore, IntentDenied


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = os.path.join(self.temp.name, "shared.db")
        self.leases = AccountLeaseStore(path)
        self.intents = IntentStore(path)
        self.cell = CellKey("user-a", "kraken", "live", "broker-account-a")

    def test_reserve_once_only(self):
        lease = self.leases.acquire(self.cell, "worker-a", now=100)
        self.intents.reserve(self.cell, lease, "unique-intent-123", now=101)
        with self.assertRaises(IntentDenied):
            self.intents.reserve(self.cell, lease, "unique-intent-123", now=102)

    def test_stale_generation_cannot_reserve(self):
        old = self.leases.acquire(self.cell, "worker-a", now=100)
        self.leases.acquire(self.cell, "worker-b", now=131)
        with self.assertRaises(IntentDenied):
            self.intents.reserve(self.cell, old, "unique-intent-124", now=132)

    def test_expired_lease_cannot_reserve(self):
        old = self.leases.acquire(self.cell, "worker-a", now=100)
        with self.assertRaises(IntentDenied):
            self.intents.reserve(self.cell, old, "unique-intent-125", now=131)

    def test_other_cells_independent(self):
        cell_b = CellKey("user-b", "alpaca", "live", "broker-account-b")
        lease_a = self.leases.acquire(self.cell, "worker-a", now=100)
        lease_b = self.leases.acquire(cell_b, "worker-b", now=100)
        self.intents.reserve(self.cell, lease_a, "same-intent-123", now=101)
        self.intents.reserve(cell_b, lease_b, "same-intent-123", now=101)

    def test_wrong_cell_lease_denied(self):
        other = CellKey("user-b", "alpaca", "live", "broker-account-b")
        lease = self.leases.acquire(self.cell, "worker-a", now=100)
        with self.assertRaises(IntentDenied):
            self.intents.reserve(other, lease, "unique-intent-126", now=101)


if __name__ == "__main__":
    unittest.main()
