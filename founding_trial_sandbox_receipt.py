"""Verify normalized, read-only Stripe sandbox first-paid-invoice evidence.

This is not an event listener, Stripe client, customer billing fulfillment, or
certificate of production readiness. All application references and provider
readers must be supplied by the trusted isolated Stripe Test Clock harness.
Never use webhook data or request-supplied fields as the independent readback.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from founding_trial_sandbox_workflow import (
    FOUNDING_STRIPE_SANDBOX_ACCOUNT,
    SandboxBillingRehearsal,
)

FOUNDING_STRIPE_TEST_PRICE = "price_1TzyLWRS5Ezp77RQI41PgONq"


@dataclass(frozen=True)
class TestBillingRun:
    """Trusted application mapping captured by the isolated simulation."""

    rehearsal: SandboxBillingRehearsal
    test_clock_id: str
    subscription_id: str
    invoice_id: str


@dataclass(frozen=True)
class SandboxInvoiceReadback:
    """Provider-observed values; a transport must reject incomplete pagination."""

    account_id: str
    livemode: bool
    test_clock_id: str
    subscription_id: str
    invoice_id: str
    price_ids: tuple[str, ...]
    positive_invoice_ids: tuple[str, ...]
    period_start: datetime
    paid_at: datetime
    status: str
    currency: str
    amount_due: int
    amount_paid: int
    amount_remaining: int


class SandboxInvoiceReader(Protocol):
    def read_invoice(self, invoice_id: str) -> SandboxInvoiceReadback | None: ...


def _provider_id(value: object, prefix: str) -> bool:
    return (
        isinstance(value, str) and value.startswith(prefix)
        and value[len(prefix):].isascii() and value[len(prefix):].isalnum()
    )


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def verify_first_sandbox_invoice(run: TestBillingRun, reader: SandboxInvoiceReader) -> bool:
    """Pass only the intended simulation's first and only $50 positive invoice.

    The billing-period start must equal the first whole Stripe second at or
    after the disclosed due time. Payment cannot precede that provider period.
    Zero-dollar trial invoices are deliberately excluded from positive IDs.
    """
    if not isinstance(run, TestBillingRun) or not isinstance(run.rehearsal, SandboxBillingRehearsal):
        return False
    rehearsal = run.rehearsal
    if (
        rehearsal.sandbox_account_id != FOUNDING_STRIPE_SANDBOX_ACCOUNT
        or type(rehearsal.amount_usd_cents) is not int
        or rehearsal.amount_usd_cents != 5000
        or not _aware(rehearsal.first_charge_at)
        or not _provider_id(run.test_clock_id, "clock_")
        or not _provider_id(run.subscription_id, "sub_")
        or not _provider_id(run.invoice_id, "in_")
    ):
        return False
    try:
        due = rehearsal.first_charge_at.astimezone(timezone.utc)
        provider_start = due.replace(microsecond=0)
        if due.microsecond:
            provider_start += timedelta(seconds=1)
        invoice = reader.read_invoice(run.invoice_id)
        return (
            isinstance(invoice, SandboxInvoiceReadback)
            and invoice.account_id == FOUNDING_STRIPE_SANDBOX_ACCOUNT
            and invoice.livemode is False
            and invoice.test_clock_id == run.test_clock_id
            and invoice.subscription_id == run.subscription_id
            and invoice.invoice_id == run.invoice_id
            and invoice.price_ids == (FOUNDING_STRIPE_TEST_PRICE,)
            and invoice.positive_invoice_ids == (run.invoice_id,)
            and _aware(invoice.period_start)
            and invoice.period_start.astimezone(timezone.utc) == provider_start
            and _aware(invoice.paid_at)
            and invoice.paid_at.astimezone(timezone.utc) >= provider_start
            and invoice.status == "paid"
            and invoice.currency == "usd"
            and type(invoice.amount_due) is int
            and invoice.amount_due == 5000
            and type(invoice.amount_paid) is int
            and invoice.amount_paid == 5000
            and type(invoice.amount_remaining) is int
            and invoice.amount_remaining == 0
        )
    except Exception:
        # This boundary never returns raw provider errors or account details.
        return False
