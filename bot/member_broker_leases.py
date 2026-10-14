"""SQLite durable account leases: storage primitive, not trading authorization.

Requires a shared durable SQLite path for all contenders. Multi-host deployment
must use a transactional shared DB instead; local SQLite cannot fence remote hosts.
"""
from __future__ import annotations

import sqlite3
import time
import math
from dataclasses import dataclass

from bot.member_broker_cells import CellKey


class LeaseDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class Lease:
    cell_id: str
    owner: str
    generation: int
    expires_at: float


class AccountLeaseStore:
    def __init__(self, db_path: str):
        if not db_path or db_path == ":memory:":
            raise ValueError("A persistent SQLite lease path is required")
        self.path = db_path

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("""CREATE TABLE IF NOT EXISTS account_leases (
            cell_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            generation INTEGER NOT NULL CHECK(generation > 0),
            expires_at REAL NOT NULL
        )""")
        return db

    def acquire(self, cell: CellKey, owner: str, ttl_seconds: float = 30, *, now: float | None = None) -> Lease:
        if not isinstance(owner, str) or not owner.strip() or not isinstance(ttl_seconds, (int, float)) or not math.isfinite(ttl_seconds) or not 1 <= ttl_seconds <= 120:
            raise LeaseDenied("Invalid lease request")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            now = time.time() if now is None else now
            row = db.execute(
                "SELECT generation, expires_at FROM account_leases WHERE cell_id=?",
                (cell.isolation_id,),
            ).fetchone()
            if row and row[1] > now:
                raise LeaseDenied("Cell lease currently held")
            generation = (row[0] + 1) if row else 1
            expiry = now + ttl_seconds
            db.execute("""INSERT INTO account_leases(cell_id, owner, generation, expires_at)
                VALUES(?,?,?,?) ON CONFLICT(cell_id) DO UPDATE SET
                owner=excluded.owner,generation=excluded.generation,expires_at=excluded.expires_at""",
                (cell.isolation_id, owner, generation, expiry))
            db.execute("COMMIT")
            return Lease(cell.isolation_id, owner, generation, expiry)
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def validate(self, lease: Lease, *, now: float | None = None) -> bool:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT owner,generation,expires_at FROM account_leases WHERE cell_id=?",
                (lease.cell_id,),
            ).fetchone()
            now = time.time() if now is None else now
            return bool(row and row[0] == lease.owner and row[1] == lease.generation
                        and row[2] == lease.expires_at and row[2] > now)
        finally:
            db.close()

    def renew(self, lease: Lease, ttl_seconds: float = 30, *, now: float | None = None) -> Lease:
        """Extend only the exact live owner/generation; stale workers fail closed."""
        if not isinstance(ttl_seconds, (int, float)) or not math.isfinite(ttl_seconds) or not 1 <= ttl_seconds <= 120:
            raise LeaseDenied("Invalid renewal TTL")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            now = time.time() if now is None else now
            new_expiry = now + ttl_seconds
            cursor = db.execute(
                """UPDATE account_leases SET expires_at=?
                   WHERE cell_id=? AND owner=? AND generation=?
                   AND expires_at=? AND expires_at>?""",
                (new_expiry, lease.cell_id, lease.owner, lease.generation, lease.expires_at, now),
            )
            if cursor.rowcount != 1:
                raise LeaseDenied("Stale or expired lease")
            db.execute("COMMIT")
            return Lease(lease.cell_id, lease.owner, lease.generation, new_expiry)
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def release(self, lease: Lease) -> bool:
        db = self._connect()
        try:
            cursor = db.execute(
                "UPDATE account_leases SET expires_at=0 WHERE cell_id=? AND owner=? AND generation=? AND expires_at=?",
                (lease.cell_id, lease.owner, lease.generation, lease.expires_at),
            )
            return cursor.rowcount == 1
        finally:
            db.close()
