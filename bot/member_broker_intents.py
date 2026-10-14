"""Durable one-time order-intent reservations for isolated member broker cells.

Pure SQLite storage primitive. This does NOT make the broker order endpoint
transactional; production transport must use stable broker client-order IDs,
broker order readback, and reconciliation before retrying uncertain outcomes.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from bot.member_broker_cells import CellKey
from bot.member_broker_leases import Lease


class IntentDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class ReservedIntent:
    cell_id: str
    intent_id: str
    lease_generation: int


class IntentStore:
    def __init__(self, path: str):
        if not path or path == ":memory:":
            raise ValueError("Persistent intent database required")
        self.path = path

    def reserve(self, cell: CellKey, lease: Lease, intent_id: str, *, now: float | None = None) -> ReservedIntent:
        if (not isinstance(intent_id, str) or not 8 <= len(intent_id) <= 128 or
                not intent_id.isascii() or not all(c.isalnum() or c in "-_" for c in intent_id)):
            raise IntentDenied("Invalid order-intent identifier")
        if lease.cell_id != cell.isolation_id:
            raise IntentDenied("Lease account mismatch")
        now = time.time() if now is None else now
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""CREATE TABLE IF NOT EXISTS account_leases (
                cell_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                generation INTEGER NOT NULL, expires_at REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS order_intent_reservations (
                cell_id TEXT NOT NULL, intent_id TEXT NOT NULL,
                lease_generation INTEGER NOT NULL, reserved_at REAL NOT NULL,
                PRIMARY KEY(cell_id, intent_id))""")
            row = conn.execute(
                "SELECT owner,generation,expires_at FROM account_leases WHERE cell_id=?",
                (cell.isolation_id,),
            ).fetchone()
            if not row or row != (lease.owner, lease.generation, lease.expires_at) or row[2] <= now:
                raise IntentDenied("Lease is stale, absent, or expired")
            conn.execute(
                "INSERT INTO order_intent_reservations(cell_id,intent_id,lease_generation,reserved_at) VALUES(?,?,?,?)",
                (cell.isolation_id, intent_id, lease.generation, now),
            )
            conn.execute("COMMIT")
            return ReservedIntent(cell.isolation_id, intent_id, lease.generation)
        except sqlite3.IntegrityError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise IntentDenied("Order intent already reserved") from exc
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def validate_and_reserve_intent(
    store: IntentStore,
    cell: CellKey,
    lease: Lease,
    intent_id: str,
    *,
    authenticated_member_id: str,
    authenticated_broker_account_id: str,
    broker_identity_attested: bool,
    cell_ready: bool,
    global_emergency_stop: bool,
    now: float | None = None,
) -> ReservedIntent:
    """Single fail-closed application boundary before durable reservation.

    Not an order placement authorization: broker-native fencing and order
    reconciliation are required before an actual trading transport is wired.
    """
    if global_emergency_stop or not cell_ready:
        raise IntentDenied("Cell unavailable")
    if not broker_identity_attested:
        raise IntentDenied("Broker identity not authenticated")
    if authenticated_member_id != cell.member_id:
        raise IntentDenied("Member mismatch")
    if authenticated_broker_account_id != cell.brokerage_account_id:
        raise IntentDenied("Broker account mismatch")
    return store.reserve(cell, lease, intent_id, now=now)
