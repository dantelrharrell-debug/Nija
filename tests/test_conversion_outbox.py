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


def test_opt_in_outbox_delivery_is_once_only(monkeypatch, tmp_path):
    from analytics.conversion_delivery import DeliveryDisabled
    from analytics import conversion_delivery

    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    assert outbox.enqueue_verified_lead({"id": "lead-opt-in", "persisted": True}, consent=True)
    delivered = []
    monkeypatch.setattr(conversion_delivery, "deliver_ga4",
                        lambda event, **kwargs: delivered.append(event) or True)
    args = dict(client_id="123.456", measurement_id="G-ABCDE12345", api_secret="secret")
    with __import__("pytest").raises(DeliveryDisabled):
        outbox.deliver_claimed("lead:lead-opt-in", **args)
    assert outbox.pending()[0]["state"] == "pending"
    assert outbox.deliver_claimed("lead:lead-opt-in", enabled=True, **args) is True
    assert outbox.deliver_claimed("lead:lead-opt-in", enabled=True, **args) is False
    assert len(delivered) == 1
    assert outbox.pending()[0]["state"] == "delivered"


def test_uncertain_delivery_remains_claimed(monkeypatch, tmp_path):
    from analytics import conversion_delivery
    import pytest

    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    assert outbox.enqueue_verified_lead({"id": "lead-uncertain", "persisted": True}, consent=True)

    def failed(_event, **_kwargs):
        raise TimeoutError("unknown_provider_acceptance")

    monkeypatch.setattr(conversion_delivery, "deliver_ga4", failed)
    args = dict(client_id="123.456", measurement_id="G-ABCDE12345", api_secret="secret", enabled=True)
    with pytest.raises(TimeoutError):
        outbox.deliver_claimed("lead:lead-uncertain", **args)
    assert outbox.pending()[0]["state"] == "claimed"
    assert outbox.deliver_claimed("lead:lead-uncertain", **args) is False


def test_invalid_attribution_does_not_claim_pending_conversion(tmp_path):
    import pytest
    engine = create_engine("sqlite:///" + str(tmp_path / "conversion.db"))
    outbox = ConversionOutbox(engine)
    assert outbox.enqueue_verified_lead({"id": "lead-invalid-client", "persisted": True}, consent=True)
    with pytest.raises(ValueError, match="invalid_client_id"):
        outbox.deliver_claimed("lead:lead-invalid-client", enabled=True,
                              client_id="unverified", measurement_id="G-ABCDE12345",
                              api_secret="test-only-secret")
    assert outbox.pending()[0]["state"] == "pending"
