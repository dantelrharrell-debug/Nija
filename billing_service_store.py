"""Durable storage for the standalone NIJA billing service.

The billing service is deliberately independent from trading runtime state.  In
production it uses a PostgreSQL URL supplied through BILLING_DATABASE_URL.  The
SQLite URL support exists only for focused tests and local development.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError


class BillingIdentityMismatch(ValueError):
    """Raised when a NIJA billing identity conflicts with durable state."""


class BillingServiceStore:
    """SQL-backed billing state with event and Checkout Session idempotency."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise RuntimeError("BILLING_DATABASE_URL is required")
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.metadata = MetaData()

        self.customers = Table(
            "billing_customers",
            self.metadata,
            Column("nija_user_id", String(128), primary_key=True),
            Column("email", String(320), nullable=False),
            Column("offer_code", String(64), nullable=False),
            Column("expected_price_id", String(128), nullable=False),
            Column("expected_product_id", String(128), nullable=False),
            Column("stripe_customer_id", String(128), nullable=True, unique=True),
            Column("stripe_subscription_id", String(128), nullable=True, unique=True),
            Column("status", String(64), nullable=False, default="not_started"),
            Column("entitled", Boolean, nullable=False, default=False),
            Column("entitlement_reason", Text, nullable=True),
            Column("current_period_end", BigInteger, nullable=True),
            Column("stripe_event_created", BigInteger, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )

        self.checkout_sessions = Table(
            "billing_checkout_sessions",
            self.metadata,
            Column("checkout_session_id", String(128), primary_key=True),
            Column("nija_user_id", String(128), nullable=False, index=True),
            Column("email", String(320), nullable=False),
            Column("offer_code", String(64), nullable=False),
            Column("expected_price_id", String(128), nullable=False),
            Column("expected_product_id", String(128), nullable=False),
            Column("stripe_customer_id", String(128), nullable=True),
            Column("stripe_subscription_id", String(128), nullable=True),
            Column("payment_status", String(64), nullable=True),
            Column("verification_status", String(64), nullable=False, default="pending"),
            Column("verification_reason", Text, nullable=True),
            Column("verified", Boolean, nullable=False, default=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint("checkout_session_id", name="uq_billing_checkout_session_id"),
        )

        self.events = Table(
            "billing_events",
            self.metadata,
            Column("event_id", String(128), primary_key=True),
            Column("event_type", String(128), nullable=False),
            Column("claimed_at", DateTime(timezone=True), nullable=False),
            Column("processed_at", DateTime(timezone=True), nullable=True),
            UniqueConstraint("event_id", name="uq_billing_event_id"),
        )

        self.metadata.create_all(self.engine)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_email(email: str) -> str:
        return str(email or "").strip().lower()

    @staticmethod
    def _row_dict(row: Any) -> Optional[dict[str, Any]]:
        if row is None:
            return None
        return dict(row._mapping)

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(select(1))

    def get_customer(self, user_id: str) -> Optional[dict[str, Any]]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.customers).where(self.customers.c.nija_user_id == user_id)
            ).first()
        return self._row_dict(row)

    def find_user_by_subscription(self, subscription_id: str) -> Optional[str]:
        if not subscription_id:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.customers.c.nija_user_id).where(
                    self.customers.c.stripe_subscription_id == subscription_id
                )
            ).first()
        return str(row[0]) if row else None

    def find_user_by_customer(self, customer_id: str) -> Optional[str]:
        if not customer_id:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.customers.c.nija_user_id).where(
                    self.customers.c.stripe_customer_id == customer_id
                )
            ).first()
        return str(row[0]) if row else None

    def get_checkout(self, session_id: str) -> Optional[dict[str, Any]]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.checkout_sessions).where(
                    self.checkout_sessions.c.checkout_session_id == session_id
                )
            ).first()
        return self._row_dict(row)

    def create_checkout(
        self,
        *,
        user_id: str,
        email: str,
        offer_code: str,
        expected_price_id: str,
        expected_product_id: str,
        session_id: str,
        customer_id: Optional[str],
    ) -> None:
        now = self._now()
        normalized_email = self._normalize_email(email)
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.customers).where(self.customers.c.nija_user_id == user_id)
            ).first()
            if existing:
                current = dict(existing._mapping)
                if self._normalize_email(current["email"]) != normalized_email:
                    raise BillingIdentityMismatch("billing email does not match existing NIJA identity")
                if current["offer_code"] != offer_code:
                    raise BillingIdentityMismatch("billing offer does not match immutable NIJA assignment")
                conn.execute(
                    update(self.customers)
                    .where(self.customers.c.nija_user_id == user_id)
                    .values(
                        expected_price_id=expected_price_id,
                        expected_product_id=expected_product_id,
                        stripe_subscription_id=None,
                        status="checkout_created",
                        entitled=False,
                        entitlement_reason="awaiting_authoritative_subscription_state",
                        current_period_end=None,
                        updated_at=now,
                    )
                )
            else:
                conn.execute(
                    insert(self.customers).values(
                        nija_user_id=user_id,
                        email=normalized_email,
                        offer_code=offer_code,
                        expected_price_id=expected_price_id,
                        expected_product_id=expected_product_id,
                        stripe_customer_id=customer_id,
                        status="checkout_created",
                        entitled=False,
                        entitlement_reason="awaiting_authoritative_subscription_state",
                        created_at=now,
                        updated_at=now,
                    )
                )

            try:
                conn.execute(
                    insert(self.checkout_sessions).values(
                        checkout_session_id=session_id,
                        nija_user_id=user_id,
                        email=normalized_email,
                        offer_code=offer_code,
                        expected_price_id=expected_price_id,
                        expected_product_id=expected_product_id,
                        stripe_customer_id=customer_id,
                        verification_status="pending",
                        verified=False,
                        created_at=now,
                        updated_at=now,
                    )
                )
            except IntegrityError as exc:
                raise BillingIdentityMismatch("Checkout Session ID already exists") from exc

    def mark_checkout_verified(
        self,
        *,
        session_id: str,
        customer_id: str,
        subscription_id: str,
        payment_status: str,
    ) -> None:
        now = self._now()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.checkout_sessions).where(
                    self.checkout_sessions.c.checkout_session_id == session_id
                )
            ).first()
            if not row:
                raise BillingIdentityMismatch("Checkout Session was not created by NIJA billing")
            session = dict(row._mapping)
            conn.execute(
                update(self.checkout_sessions)
                .where(self.checkout_sessions.c.checkout_session_id == session_id)
                .values(
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    payment_status=payment_status,
                    verification_status="validated",
                    verification_reason=None,
                    verified=True,
                    updated_at=now,
                )
            )
            customer_row = conn.execute(
                select(self.customers).where(
                    self.customers.c.nija_user_id == session["nija_user_id"]
                )
            ).first()
            customer = dict(customer_row._mapping) if customer_row else {}
            authoritative_active = str(customer.get("status") or "").lower() in {
                "active",
                "trialing",
            }
            conn.execute(
                update(self.customers)
                .where(self.customers.c.nija_user_id == session["nija_user_id"])
                .values(
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    entitled=authoritative_active,
                    entitlement_reason=(
                        "authoritative_subscription_state"
                        if authoritative_active
                        else "awaiting_authoritative_subscription_state"
                    ),
                    updated_at=now,
                )
            )

    def set_checkout_status(
        self,
        session_id: str,
        *,
        verification_status: str,
        reason: Optional[str],
        payment_status: Optional[str] = None,
        verified: bool = False,
        revoke_customer: bool = False,
    ) -> None:
        """Persist Checkout verification state without granting entitlement."""
        now = self._now()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.checkout_sessions.c.nija_user_id).where(
                    self.checkout_sessions.c.checkout_session_id == session_id
                )
            ).first()
            if not row:
                return
            user_id = str(row[0])
            values: dict[str, Any] = {
                "verification_status": verification_status,
                "verification_reason": reason,
                "verified": bool(verified),
                "updated_at": now,
            }
            if payment_status is not None:
                values["payment_status"] = payment_status
            conn.execute(
                update(self.checkout_sessions)
                .where(self.checkout_sessions.c.checkout_session_id == session_id)
                .values(**values)
            )
            if revoke_customer:
                conn.execute(
                    update(self.customers)
                    .where(self.customers.c.nija_user_id == user_id)
                    .values(
                        status=verification_status,
                        entitled=False,
                        entitlement_reason=reason,
                        updated_at=now,
                    )
                )

    def mark_checkout_mismatch(self, session_id: str, reason: str) -> None:
        self.set_checkout_status(
            session_id,
            verification_status="mismatch",
            reason=reason,
            verified=False,
            revoke_customer=True,
        )

    def apply_subscription_state(
        self,
        *,
        user_id: str,
        customer_id: Optional[str],
        subscription_id: Optional[str],
        status: str,
        offer_code: Optional[str],
        current_period_end: Optional[int],
        entitled: bool,
        reason: str,
        event_created: int,
    ) -> bool:
        """Apply only non-stale Stripe state. Returns True when state changed."""
        now = self._now()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.customers).where(self.customers.c.nija_user_id == user_id)
            ).first()
            if not row:
                return False
            current = dict(row._mapping)
            previous_created = current.get("stripe_event_created")
            if previous_created is not None and int(previous_created) > int(event_created):
                return False
            if offer_code and offer_code != current["offer_code"]:
                status = "mismatch"
                entitled = False
                reason = "subscription_offer_mismatch"

            if entitled:
                verified_checkout = conn.execute(
                    select(self.checkout_sessions.c.checkout_session_id).where(
                        (self.checkout_sessions.c.nija_user_id == user_id)
                        & (self.checkout_sessions.c.verified.is_(True))
                        & (
                            (self.checkout_sessions.c.stripe_subscription_id == subscription_id)
                            | (self.checkout_sessions.c.stripe_subscription_id.is_(None))
                        )
                    )
                ).first()
                if not verified_checkout:
                    entitled = False
                    reason = "awaiting_verified_checkout_session"
            conn.execute(
                update(self.customers)
                .where(self.customers.c.nija_user_id == user_id)
                .values(
                    stripe_customer_id=customer_id or current.get("stripe_customer_id"),
                    stripe_subscription_id=subscription_id or current.get("stripe_subscription_id"),
                    status=status,
                    entitled=bool(entitled),
                    entitlement_reason=reason,
                    current_period_end=current_period_end,
                    stripe_event_created=int(event_created),
                    updated_at=now,
                )
            )
        return True

    def claim_event(self, event_id: str, event_type: str, stale_after_seconds: int = 600) -> bool:
        """Claim a Stripe event, allowing recovery of abandoned claims."""
        now = self._now()
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    insert(self.events).values(
                        event_id=event_id,
                        event_type=event_type,
                        claimed_at=now,
                        processed_at=None,
                    )
                )
            return True
        except IntegrityError:
            pass

        cutoff = now - timedelta(seconds=max(60, stale_after_seconds))
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.events).where(self.events.c.event_id == event_id)
            ).first()
            if not row:
                return False
            existing = dict(row._mapping)
            if existing.get("processed_at") is not None:
                return False
            claimed_at = existing.get("claimed_at")
            if claimed_at is None or claimed_at > cutoff:
                return False
            conn.execute(
                update(self.events)
                .where(self.events.c.event_id == event_id)
                .values(event_type=event_type, claimed_at=now)
            )
            return True

    def finish_event(self, event_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(self.events)
                .where(self.events.c.event_id == event_id)
                .values(processed_at=self._now())
            )

    def release_event(self, event_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(self.events).where(
                    (self.events.c.event_id == event_id)
                    & (self.events.c.processed_at.is_(None))
                )
            )

    def verification_record(self, session_id: str) -> Optional[dict[str, Any]]:
        """Return the minimal record consumed by /beta-success polling."""
        with self.engine.connect() as conn:
            session_row = conn.execute(
                select(self.checkout_sessions).where(
                    self.checkout_sessions.c.checkout_session_id == session_id
                )
            ).first()
            if not session_row:
                return None
            session = dict(session_row._mapping)
            customer_row = conn.execute(
                select(self.customers).where(
                    self.customers.c.nija_user_id == session["nija_user_id"]
                )
            ).first()

        customer = dict(customer_row._mapping) if customer_row else {}
        entitled = bool(customer.get("entitled", False))
        checkout_verified = bool(session.get("verified", False))
        status = str(customer.get("status") or "pending")

        if checkout_verified and entitled:
            state = "verified"
        elif status in {"canceled", "unpaid", "past_due", "payment_failed", "expired", "mismatch"}:
            state = "revoked"
        else:
            state = "pending"

        return {
            "checkout_session_id": session_id,
            "state": state,
            "verified": state == "verified",
            "checkout_verified": checkout_verified,
            "entitled": entitled,
            "subscription_status": status,
            "offer_code": session["offer_code"],
            "verification_status": session["verification_status"],
        }
