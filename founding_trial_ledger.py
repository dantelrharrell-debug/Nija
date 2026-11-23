"""Isolated durable first-fill trial ledger. No Stripe or broker operations.

Caller must independently authenticate the member, broker ownership and live,
executed fill before invoking record_fill. This ledger does NOT verify fills,
consent, eligibility or notices. Do not expose it as a public endpoint.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from founding_trial_contract import trial_window_from_authoritative_fill


class ExecutionOwnershipConflict(ValueError):
    """A purported execution was previously assigned to another account."""


@dataclass(frozen=True)
class TrialRecord:
    member_id: str
    state: str
    execution_id: str | None
    starts_at: str | None
    ends_at: str | None


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 255):
        raise ValueError(f'{label} must contain 1..255 characters')
    if value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError(f'{label} must have no whitespace or control characters')
    return value


class FoundingTrialLedger:
    """SQLite reference implementation for synthetic/staging testing.

    Production requires shared durable storage, backup/restore, authenticated
    event adapter, consent/legal checks and transactional cross-service mapping.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path == ':memory:':
            raise ValueError('an in-memory database would not be durable')
        with closing(self._connect()) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS founding_trial_events (
                member_id TEXT PRIMARY KEY NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('trialing', 'canceled')),
                execution_id TEXT UNIQUE,
                starts_at TEXT,
                ends_at TEXT,
                CHECK ((execution_id IS NULL AND starts_at IS NULL AND ends_at IS NULL)
                    OR (execution_id IS NOT NULL AND starts_at IS NOT NULL AND ends_at IS NOT NULL))
            )""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=15000')
        return conn

    @staticmethod
    def _record(row: sqlite3.Row) -> TrialRecord:
        return TrialRecord(row['member_id'], row['state'], row['execution_id'], row['starts_at'], row['ends_at'])

    def get(self, member_id: str) -> TrialRecord | None:
        _identifier(member_id, 'member_id')
        with closing(self._connect()) as conn:
            row = conn.execute('SELECT * FROM founding_trial_events WHERE member_id = ?', (member_id,)).fetchone()
        return self._record(row) if row else None

    def record_fill(self, member_id: str, execution_id: str, executed_at: datetime) -> TrialRecord:
        """Persist the first submitted, externally verified fill per member.

        Later events never reset the window, even when older timestamps arrive.
        A discrepancy requires manual reconciliation. Cancellation is terminal.
        """
        member_id = _identifier(member_id, 'member_id')
        execution_id = _identifier(execution_id, 'execution_id')
        window = trial_window_from_authoritative_fill(executed_at)
        with closing(self._connect()) as conn:
            try:
                conn.execute('BEGIN IMMEDIATE')
                owner = conn.execute('SELECT member_id FROM founding_trial_events WHERE execution_id = ?', (execution_id,)).fetchone()
                if owner and owner['member_id'] != member_id:
                    raise ExecutionOwnershipConflict('execution is bound to another member')
                existing = conn.execute('SELECT * FROM founding_trial_events WHERE member_id = ?', (member_id,)).fetchone()
                if existing:
                    result = self._record(existing)
                else:
                    conn.execute("""INSERT INTO founding_trial_events
                        (member_id, state, execution_id, starts_at, ends_at)
                        VALUES (?, 'trialing', ?, ?, ?)""",
                        (member_id, execution_id, window.starts_at.isoformat(), window.ends_at.isoformat()))
                    result = TrialRecord(member_id, 'trialing', execution_id, window.starts_at.isoformat(), window.ends_at.isoformat())
                conn.execute('COMMIT')
                return result
            except Exception:
                conn.execute('ROLLBACK')
                raise

    def cancel(self, member_id: str) -> TrialRecord:
        """Record cancellation even if no qualifying live trade ever occurs."""
        member_id = _identifier(member_id, 'member_id')
        with closing(self._connect()) as conn:
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute("""INSERT INTO founding_trial_events (member_id, state)
                    VALUES (?, 'canceled')
                    ON CONFLICT(member_id) DO UPDATE SET state = 'canceled'""", (member_id,))
                row = conn.execute('SELECT * FROM founding_trial_events WHERE member_id = ?', (member_id,)).fetchone()
                conn.execute('COMMIT')
                return self._record(row)
            except Exception:
                conn.execute('ROLLBACK')
                raise
