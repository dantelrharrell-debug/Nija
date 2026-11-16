"""Fail-closed, payment-bound Resend receipt relay for NIJA billing.

Designed for the existing standalone billing service. This module cannot process
browser payment claims, replay Stripe events, grant entitlements, or send unless
an operator separately enables the guarded worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError

EVENT_NAME = "nija.payment.receipt_verified.v1"
PURPOSE = "receipt_v1"


def _field(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _id(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    return str(_field(obj, "id", "") or "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class VerifiedInvoiceReceipt:
    invoice_id: str
    email: str
    amount_cents: int
    currency: str
    purchase_name: str

    @property
    def key(self) -> str:
        return hashlib.sha256(("nija:stripe:invoice:" + self.invoice_id + ":" + PURPOSE).encode()).hexdigest()

    def payload(self) -> dict[str, str | bool | int]:
        return {
            "paid": True,
            "amount_cents": self.amount_cents,
            "purchase_name": self.purchase_name,
            "amount_paid": "${:,.2f}".format(self.amount_cents / 100),
            "payment_reference": self.invoice_id,
            "provider": "stripe",
        }


def verified_invoice_from_stripe(stripe: Any, billing_store: Any, event_invoice: Any) -> VerifiedInvoiceReceipt | None:
    """Re-read the actual paid invoice and verify its bound NIJA identity.

    The caller MUST first verify the Stripe-Signature and reconcile billing state.
    Neither the webhook's untrusted fields nor an email alone establishes a buyer.
    """
    invoice_id = _id(event_invoice)
    if not invoice_id.startswith("in_") or len(invoice_id) > 128:
        return None
    invoice = stripe.Invoice.retrieve(invoice_id)
    if _id(invoice) != invoice_id or _field(invoice, "livemode") is not True:
        return None
    amount = _field(invoice, "amount_paid", 0)
    if type(amount) is not int or amount <= 0 or amount > 100_000_000:
        return None
    if _field(invoice, "currency", "").lower() != "usd":
        return None
    if _field(invoice, "paid") is not True or _field(invoice, "status") != "paid":
        return None
    if _field(invoice, "amount_remaining", 0) != 0:
        return None
    subscription_id = _id(_field(invoice, "subscription"))
    customer_id = _id(_field(invoice, "customer"))
    if not subscription_id.startswith("sub_") or not customer_id.startswith("cus_"):
        return None
    user_id = billing_store.find_user_by_subscription(subscription_id)
    if not user_id:
        return None
    customer = billing_store.get_customer(user_id)
    if not customer or customer.get("stripe_subscription_id") != subscription_id:
        return None
    if customer.get("stripe_customer_id") != customer_id or customer.get("entitled") is not True:
        return None
    offer = str(customer.get("offer_code") or "")
    if offer not in {"founding_beta", "standard_beta", "standard_beta_v2"}:
        return None
    email = str(customer.get("email") or "").strip().lower()
    if len(email) > 320 or email.count("@") != 1 or any(c.isspace() or ord(c) < 33 for c in email):
        return None
    name = {"founding_beta": "NIJA Founding 100 membership",
            "standard_beta": "NIJA standard membership",
            "standard_beta_v2": "NIJA standard membership"}[offer]
    return VerifiedInvoiceReceipt(invoice_id, email, amount, "usd", name)


class ReceiptOutbox:
    """Persist one row per invoice/purpose, with an at-most-once send attempt.

    `sending` and `uncertain` are intentionally NEVER auto-retried. A timeout
    could mean the provider accepted the event; reconciliation is required.
    """

    def __init__(self, engine):
        self.engine = engine
        meta = MetaData()
        self.table = Table(
            "billing_verified_receipt_outbox", meta,
            Column("key", String(64), primary_key=True),
            Column("invoice_id", String(128), nullable=False, unique=True),
            Column("email", String(320), nullable=False),
            Column("amount_cents", Integer, nullable=False),
            Column("currency", String(3), nullable=False),
            Column("purchase_name", String(100), nullable=False),
            Column("state", String(20), nullable=False),
            Column("provider_event_acknowledgment", String(128)),
            Column("error_code", Text),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        meta.create_all(engine)

    def enqueue(self, receipt: VerifiedInvoiceReceipt) -> bool:
        if not isinstance(receipt, VerifiedInvoiceReceipt) or receipt.amount_cents <= 0:
            raise ValueError("verified_positive_invoice_required")
        with self.engine.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(insert(self.table).values(
                        key=receipt.key, invoice_id=receipt.invoice_id,
                        email=receipt.email, amount_cents=receipt.amount_cents,
                        currency=receipt.currency, purchase_name=receipt.purchase_name,
                        state="queued", created_at=_now(), updated_at=_now(),
                    ))
                return True
            except IntegrityError:
                row = conn.execute(select(self.table).where(self.table.c.key == receipt.key)).mappings().first()
                if not row or (row["invoice_id"], row["email"], row["amount_cents"],
                               row["currency"], row["purchase_name"]) != (
                        receipt.invoice_id, receipt.email, receipt.amount_cents,
                        receipt.currency, receipt.purchase_name):
                    raise ValueError("receipt_invoice_identity_conflict")
                return False

    def pending(self, limit: int = 10) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(self.table).where(self.table.c.state == "queued")
                                .order_by(self.table.c.created_at).limit(min(max(limit, 1), 25))).mappings().all()
            return [dict(row) for row in rows]

    def claim(self, key: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(update(self.table).where(
                (self.table.c.key == key) & (self.table.c.state == "queued"))
                .values(state="sending", updated_at=_now()))
            return result.rowcount == 1

    def finish(self, key: str, *, provider_acknowledgment: str | None = None, error_code: str | None = None) -> None:
        state = "accepted" if provider_acknowledgment else "uncertain"
        with self.engine.begin() as conn:
            conn.execute(update(self.table).where(
                (self.table.c.key == key) & (self.table.c.state == "sending"))
                .values(state=state, provider_event_acknowledgment=provider_acknowledgment,
                        error_code=(error_code or "")[:100], updated_at=_now()))

    def status_counts(self) -> dict[str, int]:
        from sqlalchemy import func
        with self.engine.connect() as conn:
            return {state: count for state, count in conn.execute(
                select(self.table.c.state, func.count()).group_by(self.table.c.state)).all()}


def emit_resend_event(email: str, receipt: VerifiedInvoiceReceipt, *, api_key: str, opener=None) -> str:
    """Use Resend Events, not the email API; accepted does NOT mean delivered."""
    if not api_key:
        raise RuntimeError("resend_not_configured")
    req = urllib.request.Request(
        "https://api.resend.com/events/send",
        data=json.dumps({"event": EVENT_NAME, "email": email,
                         "payload": receipt.payload()}, separators=(",", ":")).encode(),
        headers={"Authorization": "Bearer " + api_key,
                 "Content-Type": "application/json"},
        method="POST",
    )
    with (opener or urllib.request.urlopen)(req, timeout=10) as response:
        if response.status != 202:
            raise RuntimeError("provider_not_accepted")
        returned = json.loads(response.read())
        # Resend Events /events/send returns {object:"event",event:"<name>"},
        # not a message ID or proof that email was delivered.
        if returned.get("object") != "event" or returned.get("event") != EVENT_NAME:
            raise RuntimeError("provider_event_ack_invalid")
        return "accepted:" + EVENT_NAME


def process_one(outbox: ReceiptOutbox, record: dict, *, sender=None) -> bool:
    """One controlled send, never an automatic ambiguous retry."""
    if not outbox.claim(record["key"]):
        return False
    receipt = VerifiedInvoiceReceipt(
        record["invoice_id"], record["email"], record["amount_cents"],
        record["currency"], record["purchase_name"])
    try:
        provider_acknowledgment = (sender or (lambda email, rec: emit_resend_event(
            email, rec, api_key=os.environ.get("RESEND_API_KEY", ""))))(record["email"], receipt)
        if not isinstance(provider_acknowledgment, str) or not provider_acknowledgment:
            raise RuntimeError("provider_event_ack_missing")
        outbox.finish(record["key"], provider_acknowledgment=provider_acknowledgment)
        return True
    except Exception as exc:
        outbox.finish(record["key"], error_code=type(exc).__name__)
        return False


def process_batch_from_env(outbox: ReceiptOutbox) -> dict[str, int]:
    """Explicit operator action; disabled until both sender ownership and proof."""
    mode = os.getenv("NIJA_VERIFIED_PAYMENT_SEND_MODE", "disabled")
    if mode not in ("controlled", "enabled"):
        raise RuntimeError("verified_payment_sending_disabled")
    if os.getenv("NIJA_VERIFIED_PAYMENT_RECEIPT_CERTIFIED") != "true":
        raise RuntimeError("verified_payment_sender_not_certified")
    if not os.getenv("RESEND_API_KEY"):
        raise RuntimeError("resend_not_configured")
    allow = {e.strip().lower() for e in os.getenv("NIJA_PAYMENT_TEST_RECIPIENTS", "").split(",") if e.strip()}
    if mode == "controlled" and not allow:
        raise RuntimeError("controlled_recipient_allowlist_required")
    sent = failed = 0
    for row in outbox.pending(limit=10):
        if mode == "controlled" and row["email"] not in allow:
            continue
        if process_one(outbox, row):
            sent += 1
        else:
            failed += 1
    return {"accepted": sent, "uncertain": failed}