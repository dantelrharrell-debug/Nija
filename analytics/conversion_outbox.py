"""Durable, fail-closed staging outbox for NIJA conversion attribution.

No Google Analytics / Google Ads network requests occur here. Only event
identity and minimal non-PII payloads are stored. The caller must verify
consent and authoritative source evidence before enqueueing.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError

from analytics.verified_conversion_events import (
    verified_course_purchase, verified_lead_event,
)


class ConversionOutbox:
    def __init__(self, engine):
        self.engine = engine
        metadata = MetaData()
        self.table = Table(
            "nija_conversion_outbox", metadata,
            Column("dedupe_key", String(256), primary_key=True),
            Column("event_name", String(80), nullable=False),
            Column("payload_json", Text, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("state", String(16), nullable=False, default="pending"),
            Column("claimed_at", DateTime(timezone=True), nullable=True),
            Column("delivered_at", DateTime(timezone=True), nullable=True),
        )
        metadata.create_all(engine)

    def _enqueue(self, event):
        if event is None:
            return False
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(self.table).values(
                    dedupe_key=event["dedupe_key"],
                    event_name=event["event_name"],
                    payload_json=json.dumps(event["parameters"], sort_keys=True),
                    created_at=datetime.now(timezone.utc),
                    state="pending",
                ))
            return True
        except IntegrityError:
            return False

    def enqueue_verified_lead(self, persisted_lead, *, consent):
        """Only call with a server-side persisted lead, never a browser claim."""
        return self._enqueue(verified_lead_event(persisted_lead, consent=consent))

    def enqueue_verified_course(self, ledger, session_id, *, consent):
        """Caller must freshly reconcile Stripe and verify refunds/revocation.

        Do not invoke from an unverified redirect or raw webhook payload.
        Billing integration remains disabled pending provenance and consent review.
        """
        record = ledger.get(session_id)
        if not record:
            return False
        return self._enqueue(verified_course_purchase(
            {**record, "session_id": session_id}, consent=consent
        ))

    def claim(self, dedupe_key):
        """Atomically claim a pending row; concurrent workers cannot both claim.

        There is intentionally no automatic lease expiry: a crash after an
        external send could otherwise lead to an unverified duplicate. Manual
        recovery must check the provider's delivery evidence first.
        """
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.table).where(
                    self.table.c.dedupe_key == dedupe_key,
                    self.table.c.state == "pending",
                ).values(state="claimed", claimed_at=now)
            )
            return result.rowcount == 1

    def mark_delivered(self, dedupe_key):
        """Only a claimed event can be acknowledged after provider acceptance."""
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.table).where(
                    self.table.c.dedupe_key == dedupe_key,
                    self.table.c.state == "claimed",
                ).values(state="delivered", delivered_at=datetime.now(timezone.utc))
            )
            return result.rowcount == 1

    def pending(self):
        """Read-only inspection; no publishing or implicit retries."""
        with self.engine.connect() as connection:
            rows = connection.execute(select(self.table).order_by(
                self.table.c.created_at
            )).all()
        return [
            {"dedupe_key": row.dedupe_key, "event_name": row.event_name,
             "parameters": json.loads(row.payload_json), "state": row.state}
            for row in rows
        ]
