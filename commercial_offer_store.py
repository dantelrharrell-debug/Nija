"""Persistent NIJA commercial-offer assignment.

Commercial pricing is intentionally independent from legacy/internal feature tiers.
Each user receives one immutable-at-signup offer assignment so later public-price
changes do not silently reprice founding beta users.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from pricing_policy import (
    BETA_TRIAL_DAYS,
    FOUNDING_BETA_LIMIT,
    FOUNDING_BETA_MONTHLY_USD,
    FOUNDING_BETA_OFFER,
    STANDARD_BETA_MONTHLY_USD,
    STANDARD_BETA_OFFER,
)


@dataclass(frozen=True)
class OfferAssignment:
    user_id: str
    offer_code: str
    price_usd: Decimal
    trial_days: int
    cohort_position: Optional[int]
    assigned_at: str

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "offer_code": self.offer_code,
            "price_usd": float(self.price_usd),
            "trial_days": self.trial_days,
            "cohort_position": self.cohort_position,
            "assigned_at": self.assigned_at,
            "price_locked": True,
        }


class CommercialOfferStore:
    """SQLite-backed offer assignment store using the existing NIJA user DB file."""

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
                CREATE TABLE IF NOT EXISTS commercial_offer_assignments (
                    user_id TEXT PRIMARY KEY,
                    offer_code TEXT NOT NULL,
                    price_usd_cents INTEGER NOT NULL,
                    trial_days INTEGER NOT NULL DEFAULT 0,
                    cohort_position INTEGER,
                    assigned_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_commercial_offer_cohort_position "
                "ON commercial_offer_assignments(cohort_position) "
                "WHERE cohort_position IS NOT NULL"
            )
            conn.commit()

    def get_assignment(self, user_id: str) -> Optional[OfferAssignment]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT user_id, offer_code, price_usd_cents, trial_days, cohort_position, assigned_at "
                "FROM commercial_offer_assignments WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_assignment(row) if row else None

    def assign_beta_offer(self, user_id: str) -> OfferAssignment:
        """Atomically assign founding beta slots 1-100, then standard beta.

        Repeated calls for the same user return the original assignment.  The
        founding cohort count is based on persisted assignments, not process
        memory, so restarts cannot reset the first-100 counter.
        """
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT user_id, offer_code, price_usd_cents, trial_days, cohort_position, assigned_at "
                "FROM commercial_offer_assignments WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if existing:
                conn.commit()
                return self._row_to_assignment(existing)

            founding_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM commercial_offer_assignments WHERE offer_code = ?",
                    (FOUNDING_BETA_OFFER,),
                ).fetchone()[0]
            )
            assigned_at = datetime.now(timezone.utc).isoformat()

            if founding_count < FOUNDING_BETA_LIMIT:
                offer_code = FOUNDING_BETA_OFFER
                price = FOUNDING_BETA_MONTHLY_USD
                trial_days = BETA_TRIAL_DAYS
                cohort_position: Optional[int] = founding_count + 1
            else:
                offer_code = STANDARD_BETA_OFFER
                price = STANDARD_BETA_MONTHLY_USD
                trial_days = 0
                cohort_position = None

            cents = int(price * 100)
            conn.execute(
                "INSERT INTO commercial_offer_assignments "
                "(user_id, offer_code, price_usd_cents, trial_days, cohort_position, assigned_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, offer_code, cents, trial_days, cohort_position, assigned_at),
            )
            conn.commit()

        return OfferAssignment(
            user_id=user_id,
            offer_code=offer_code,
            price_usd=price,
            trial_days=trial_days,
            cohort_position=cohort_position,
            assigned_at=assigned_at,
        )

    def founding_beta_claimed_count(self) -> int:
        with closing(self._connect()) as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM commercial_offer_assignments WHERE offer_code = ?",
                    (FOUNDING_BETA_OFFER,),
                ).fetchone()[0]
            )

    @staticmethod
    def _row_to_assignment(row: sqlite3.Row) -> OfferAssignment:
        return OfferAssignment(
            user_id=str(row["user_id"]),
            offer_code=str(row["offer_code"]),
            price_usd=Decimal(int(row["price_usd_cents"])) / Decimal(100),
            trial_days=int(row["trial_days"]),
            cohort_position=(int(row["cohort_position"]) if row["cohort_position"] is not None else None),
            assigned_at=str(row["assigned_at"]),
        )


_store: Optional[CommercialOfferStore] = None


def get_commercial_offer_store(db_path: str = "users.db") -> CommercialOfferStore:
    global _store
    if _store is None or _store.db_path != db_path:
        _store = CommercialOfferStore(db_path=db_path)
    return _store
