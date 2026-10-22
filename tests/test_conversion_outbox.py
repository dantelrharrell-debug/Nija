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
    assert rows[0]["state"] == "pending"
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


def test_atomic_claim_and_acknowledgment(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    first = ConversionOutbox(engine)
    second = ConversionOutbox(engine)
    assert first.enqueue_verified_lead({"id": "lead-123", "persisted": True}, consent=True)
    assert first.mark_delivered("lead:lead-123") is False
    assert first.claim("lead:lead-123") is True
    assert second.claim("lead:lead-123") is False
    assert second.pending()[0]["state"] == "claimed"
    assert second.mark_delivered("lead:lead-123") is True
    assert first.mark_delivered("lead:lead-123") is False
    assert first.claim("lead:lead-123") is False
    assert first.pending()[0]["state"] == "delivered"


def test_nonexistent_claim_and_ack_fail_closed(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    assert outbox.claim("lead:missing") is False
    assert outbox.mark_delivered("lead:missing") is False


def test_reconciled_course_requires_fresh_verified_stripe(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import course_fulfillment

    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    ledger = FakeLedger({"status": "paid", "granted": True})
    stripe = SimpleNamespace()

    monkeypatch.setattr(course_fulfillment, "reconcile_session",
                        lambda _stripe, _ledger, sid: {"session_id": sid, "paid": False})
    assert outbox.enqueue_reconciled_course(stripe, ledger, "cs_verified", consent=True) is False
    assert outbox.pending() == []

    monkeypatch.setattr(course_fulfillment, "reconcile_session",
                        lambda _stripe, _ledger, sid: {"session_id": "cs_other", "paid": True})
    assert outbox.enqueue_reconciled_course(stripe, ledger, "cs_verified", consent=True) is False

    monkeypatch.setattr(course_fulfillment, "reconcile_session",
                        lambda _stripe, _ledger, sid: {"session_id": sid, "paid": True})
    assert outbox.enqueue_reconciled_course(stripe, ledger, "cs_verified", consent=False) is False
    assert outbox.enqueue_reconciled_course(stripe, ledger, "cs_verified", consent=True) is True
    assert outbox.enqueue_reconciled_course(stripe, ledger, "cs_verified", consent=True) is False
    assert len(outbox.pending()) == 1


def test_reconciliation_error_never_queues_conversion(monkeypatch, tmp_path):
    import course_fulfillment

    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)

    def unavailable(_stripe, _ledger, _sid):
        raise RuntimeError("stripe_unavailable")

    monkeypatch.setattr(course_fulfillment, "reconcile_session", unavailable)
    import pytest
    with pytest.raises(RuntimeError, match="stripe_unavailable"):
        outbox.enqueue_reconciled_course(object(), FakeLedger({"status": "paid", "granted": True}),
                                         "cs_123", consent=True)
    assert outbox.pending() == []
