"""Durable cell lease tests using only temporary SQLite databases."""
import os
import sqlite3
import threading
import tempfile
import time
import unittest

from bot.member_broker_cells import CellKey
from bot.member_broker_leases import AccountLeaseStore, LeaseDenied


class AccountLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AccountLeaseStore(os.path.join(self.temp.name, "leases.sqlite3"))
        self.cell = CellKey("member1", "kraken", "live", "account1")

    def _run_while_sqlite_locked(self, operation, *, lock_mode="IMMEDIATE"):
        blocker = sqlite3.connect(self.store.path, isolation_level=None)
        blocker.execute(f"BEGIN {lock_mode}")
        started = threading.Event()
        outcome = []

        def run():
            started.set()
            try:
                outcome.append(operation())
            except Exception as exc:
                outcome.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            time.sleep(1.1)
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        return outcome[0]

    def test_competing_owner_denied_until_expiration(self):
        original = self.store.acquire(self.cell, "worker-a", now=100)
        with self.assertRaises(LeaseDenied):
            self.store.acquire(self.cell, "worker-b", now=101)
        replacement = self.store.acquire(self.cell, "worker-b", now=131)
        self.assertGreater(replacement.generation, original.generation)
        self.assertFalse(self.store.validate(original, now=131))
        self.assertTrue(self.store.validate(replacement, now=131))

    def test_stale_release_cannot_delete_new_lease(self):
        old = self.store.acquire(self.cell, "worker-a", now=100)
        current = self.store.acquire(self.cell, "worker-a", now=131)
        self.assertFalse(self.store.release(old))
        self.assertTrue(self.store.validate(current, now=132))

    def test_independent_accounts(self):
        other = CellKey("member2", "alpaca", "live", "account2")
        a = self.store.acquire(self.cell, "worker-a", now=100)
        b = self.store.acquire(other, "worker-b", now=100)
        self.assertTrue(self.store.validate(a, now=105))
        self.assertTrue(self.store.validate(b, now=105))

    def test_release_and_reacquire_increments_generation(self):
        a = self.store.acquire(self.cell, "worker-a", now=100)
        self.assertTrue(self.store.release(a))
        b = self.store.acquire(self.cell, "worker-b", now=100)
        self.assertEqual(b.generation, a.generation + 1)

    def test_renewal_rejects_previous_token(self):
        old = self.store.acquire(self.cell, "worker-a", now=100)
        renewed = self.store.renew(old, now=110)
        self.assertTrue(self.store.validate(renewed, now=120))
        self.assertFalse(self.store.validate(old, now=120))
        with self.assertRaises(LeaseDenied):
            self.store.renew(old, now=120)

    def test_expired_lease_cannot_renew(self):
        old = self.store.acquire(self.cell, "worker-a", now=100)
        with self.assertRaises(LeaseDenied):
            self.store.renew(old, now=131)

    def test_acquire_uses_time_after_waiting_for_write_lock(self):
        self.store.acquire(self.cell, "worker-a", ttl_seconds=1)
        result = self._run_while_sqlite_locked(
            lambda: self.store.acquire(self.cell, "worker-b", ttl_seconds=1),
        )
        self.assertNotIsInstance(result, Exception)
        self.assertEqual(result.owner, "worker-b")

    def test_renew_uses_time_after_waiting_for_write_lock(self):
        lease = self.store.acquire(self.cell, "worker-a", ttl_seconds=1)
        result = self._run_while_sqlite_locked(lambda: self.store.renew(lease))
        self.assertIsInstance(result, LeaseDenied)

    def test_validate_uses_time_after_waiting_for_read_lock(self):
        lease = self.store.acquire(self.cell, "worker-a", ttl_seconds=1)
        result = self._run_while_sqlite_locked(
            lambda: self.store.validate(lease),
            lock_mode="EXCLUSIVE",
        )
        self.assertFalse(result)

    def test_invalid_nonfinite_ttl_rejected(self):
        for ttl in (float("nan"), float("inf"), float("-inf"), "30"):
            with self.assertRaises(LeaseDenied):
                self.store.acquire(self.cell, "worker-a", ttl_seconds=ttl, now=100)
        valid = self.store.acquire(self.cell, "worker-a", now=100)
        for ttl in (float("nan"), float("inf"), "30"):
            with self.assertRaises(LeaseDenied):
                self.store.renew(valid, ttl_seconds=ttl, now=105)

    def test_no_ephemeral_lease_database(self):
        with self.assertRaises(ValueError):
            AccountLeaseStore(":memory:")


if __name__ == "__main__":
    unittest.main()
