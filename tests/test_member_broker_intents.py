"""Tests durable order intent replay protection without broker calls."""
import os
import sqlite3
import threading
import tempfile
import time
import unittest

from bot.member_broker_cells import CellKey
from bot.member_broker_leases import AccountLeaseStore
from bot.member_broker_intents import IntentStore, IntentDenied, validate_and_reserve_intent


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = os.path.join(self.temp.name, "shared.db")
        self.leases = AccountLeaseStore(path)
        self.intents = IntentStore(path)
        self.cell = CellKey("user-a", "kraken", "live", "broker-account-a")

    def test_reserve_uses_time_after_waiting_for_write_lock(self):
        lease = self.leases.acquire(self.cell, "worker-a", ttl_seconds=1)
        blocker = sqlite3.connect(self.intents.path, isolation_level=None)
        blocker.execute(
            """CREATE TABLE IF NOT EXISTS order_intent_reservations (
                cell_id TEXT NOT NULL, intent_id TEXT NOT NULL,
                lease_generation INTEGER NOT NULL, reserved_at REAL NOT NULL,
                PRIMARY KEY(cell_id, intent_id))"""
        )
        blocker.execute("BEGIN IMMEDIATE")
        started = threading.Event()
        outcome = []

        def reserve():
            started.set()
            try:
                outcome.append(self.intents.reserve(self.cell, lease, "lock-expiry-123"))
            except Exception as exc:
                outcome.append(exc)

        worker = threading.Thread(target=reserve)
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            time.sleep(1.1)
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome[0], IntentDenied)

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

    def test_validation_blocks_cross_member_before_reservation(self):
        lease = self.leases.acquire(self.cell, "worker-a", now=100)
        args = dict(authenticated_member_id="other", authenticated_broker_account_id="broker-account-a",
                    broker_identity_attested=True, cell_ready=True, global_emergency_stop=False, now=101)
        with self.assertRaises(IntentDenied):
            validate_and_reserve_intent(self.intents, self.cell, lease, "intent-validated-1", **args)
        args["authenticated_member_id"] = "user-a"
        validate_and_reserve_intent(self.intents, self.cell, lease, "intent-validated-1", **args)

    def test_global_stop_blocks_reservation(self):
        lease = self.leases.acquire(self.cell, "worker-a", now=100)
        with self.assertRaises(IntentDenied):
            validate_and_reserve_intent(
                self.intents, self.cell, lease, "intent-validated-2",
                authenticated_member_id="user-a", authenticated_broker_account_id="broker-account-a",
                broker_identity_attested=True, cell_ready=True, global_emergency_stop=True, now=101)

    def test_wrong_cell_lease_denied(self):
        other = CellKey("user-b", "alpaca", "live", "broker-account-b")
        lease = self.leases.acquire(self.cell, "worker-a", now=100)
        with self.assertRaises(IntentDenied):
            self.intents.reserve(other, lease, "unique-intent-126", now=101)


if __name__ == "__main__":
    unittest.main()
