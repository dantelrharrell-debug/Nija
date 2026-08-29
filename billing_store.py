"""Persistent billing state for NIJA web subscriptions.

This module stores Stripe identifiers and subscription state separately from
internal NIJA trading-permission tiers and commercial offer assignments.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class BillingRecord:
    user_id: str
    provider: str
    customer_id: Optional[str]
    subscription_id: Optional[str]
    checkout_session_id: Optional[str]
    status: str
    offer_code: Optional[str]
    current_period_end: Optional[int]
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "provider": self.provider,
            "customer_id": self.customer_id,
            "subscription_id": self.subscription_id,
            "checkout_session_id": self.checkout_session_id,
            "status": self.status,
            "offer_code": self.offer_code,
            "current_period_end": self.current_period_end,
            "updated_at": self.updated_at,
        }


class BillingStore:
    def __init__(self, db_path: str = "users.db") -> None:
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_subscriptions (
                    user_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'stripe',
                    customer_id TEXT,
                    subscription_id TEXT,
                    checkout_session_id TEXT,
                    status TEXT NOT NULL,
                    offer_code TEXT,
                    current_period_end INTEGER,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_subscription_id "
                "ON billing_subscriptions(subscription_id) "
                "WHERE subscription_id IS NOT NULL"
            )
            conn.commit()

    def upsert(
        self,
        *,
        user_id: str,
        status: str,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        checkout_session_id: Optional[str] = None,
        offer_code: Optional[str] = None,
        current_period_end: Optional[int] = None,
    ) -> BillingRecord:
        updated_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO billing_subscriptions (
                    user_id, provider, customer_id, subscription_id,
                    checkout_session_id, status, offer_code,
                    current_period_end, updated_at
                ) VALUES (?, 'stripe', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    customer_id = COALESCE(excluded.customer_id, billing_subscriptions.customer_id),
                    subscription_id = COALESCE(excluded.subscription_id, billing_subscriptions.subscription_id),
                    checkout_session_id = COALESCE(excluded.checkout_session_id, billing_subscriptions.checkout_session_id),
                    status = excluded.status,
                    offer_code = COALESCE(excluded.offer_code, billing_subscriptions.offer_code),
                    current_period_end = COALESCE(excluded.current_period_end, billing_subscriptions.current_period_end),
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    customer_id,
                    subscription_id,
                    checkout_session_id,
                    status,
                    offer_code,
                    current_period_end,
                    updated_at,
                ),
            )
            conn.commit()
        record = self.get(user_id)
        if record is None:
            raise RuntimeError("Billing record was not persisted")
        return record

    def get(self, user_id: str) -> Optional[BillingRecord]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT user_id, provider, customer_id, subscription_id,
                       checkout_session_id, status, offer_code,
                       current_period_end, updated_at
                FROM billing_subscriptions WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return self._row(row) if row else None

    def find_user_by_subscription(self, subscription_id: str) -> Optional[str]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT user_id FROM billing_subscriptions WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> BillingRecord:
        return BillingRecord(
            user_id=str(row["user_id"]),
            provider=str(row["provider"]),
            customer_id=row["customer_id"],
            subscription_id=row["subscription_id"],
            checkout_session_id=row["checkout_session_id"],
            status=str(row["status"]),
            offer_code=row["offer_code"],
            current_period_end=(
                int(row["current_period_end"])
                if row["current_period_end"] is not None
                else None
            ),
            updated_at=str(row["updated_at"]),
        )


_store: Optional[BillingStore] = None


def get_billing_store(db_path: str = "users.db") -> BillingStore:
    global _store
    if _store is None or _store.db_path != db_path:
        _store = BillingStore(db_path=db_path)
    return _store
