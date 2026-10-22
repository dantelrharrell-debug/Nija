"""Durable, fail-closed staging outbox for NIJA conversion attribution.

No Google Analytics / Google Ads network requests occur here. This table stores
only event identity and minimal non-PII payloads. The calling workflow must
verify consent and the authoritative source record before enqueueing.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, insert, select
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
        )
        metadata.create_all(engine)

    def _enqueue(self, event):
        if event is None:
            return False
        # Database primary key, not an in-memory cache, ensures replay safety.
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(self.table).values(
                    dedupe_key=event["dedupe_key"],
                    event_name=event["event_name"],
                    payload_json=json.dumps(event["parameters"], sort_keys=True),
                    created_at=datetime.now(timezone.utc),
                ))
            return True
        except IntegrityError:
            return False

    def enqueue_verified_lead(self, persisted_lead, *, consent):
        """Only call with a server-side persisted lead, never a browser claim."""
        return self._enqueue(verified_lead_event(persisted_lead, consent=consent))

    def enqueue_verified_course(self, ledger, session_id, *, consent):
        """Read the authoritative ledger; caller must freshly reconcile Stripe.

        Never invoke from an unverified redirect or raw webhook payload.
        This is intentionally NOT wired to billing until consent and attribution
        capture plus refund/revocation policy are reviewed.
        """
        record = ledger.get(session_id)
        if not record:
            return False
        return self._enqueue(verified_course_purchase(
            {**record, "session_id": session_id}, consent=consent
        ))

    def pending(self):
        """Read-only inspection; no publishing or implicit retries."""
        with self.engine.connect() as connection:
            rows = connection.execute(select(self.table).order_by(
                self.table.c.created_at
            )).all()
        return [
            {"dedupe_key": row.dedupe_key, "event_name": row.event_name,
             "parameters": json.loads(row.payload_json)}
            for row in rows
        ]
