"""Regression tests for durable, consent-gated conversion staging."""
from sqlalchemy import create_engine

from analytics.conversion_outbox import ConversionOutbox


class FakeLedger:
    def __init__(self, row):
        self.row = row

    def get(self, session_id):
        return self.row


def test_duplicate_lead_is_staged_once(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    lead = {"id": "lead-abc", "persisted": True, "email": "private@example.com"}
    assert outbox.enqueue_verified_lead(lead, consent=True) is True
    assert outbox.enqueue_verified_lead(lead, consent=True) is False
    rows = outbox.pending()
    assert len(rows) == 1
    assert "private@example.com" not in str(rows)


def test_consent_and_payment_gate_fail_closed(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    paid = {"status": "paid", "granted": True}
    assert outbox.enqueue_verified_course(FakeLedger(paid), "cs_123", consent=False) is False
    assert outbox.enqueue_verified_course(
        FakeLedger({"status": "pending", "granted": False}), "cs_123", consent=True
    ) is False
    assert outbox.pending() == []


def test_paid_course_dedup_survives_reinstantiation(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    ledger = FakeLedger({"status": "paid", "granted": True, "customer_email": "secret@example.com"})
    assert outbox.enqueue_verified_course(ledger, "cs_123", consent=True) is True
    assert ConversionOutbox(engine).enqueue_verified_course(ledger, "cs_123", consent=True) is False
    rows = outbox.pending()
    assert rows[0]["parameters"]["transaction_id"] == "cs_123"
    assert "secret@example.com" not in str(rows)
