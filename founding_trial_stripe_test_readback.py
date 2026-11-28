"""GET-only Stripe Test Clock readback for the standalone Founding 100 harness."""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from founding_trial_sandbox_receipt import SandboxInvoiceReadback, TestBillingRun, verify_first_sandbox_invoice
from founding_trial_sandbox_workflow import FOUNDING_STRIPE_SANDBOX_ACCOUNT, SandboxBillingRehearsal

API = "https://api.stripe.com"
VERSION = "2025-06-30.basil"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _identifier(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"[A-Za-z0-9]{1,100}", value):
        raise ValueError("invalid Stripe sandbox reference")
    return value


def _timestamp(value):
    if type(value) is not int or value <= 0:
        raise ValueError("invalid Stripe timestamp")
    return datetime.fromtimestamp(value, timezone.utc)


def _minor(value):
    if type(value) is not int or value < 0:
        raise ValueError("invalid Stripe amount")
    return value


def _test_entity(value, kind, entity_id=None):
    if (value["object"] != kind or value["livemode"] is not False
            or (entity_id is not None and value["id"] != entity_id)):
        raise ValueError("provider evidence not from the expected sandbox object")
    return value


def _invoice_subscription(invoice):
    parent = invoice["parent"]
    if parent["type"] != "subscription_details":
        raise ValueError("Stripe invoice is not linked to a subscription")
    return parent["subscription_details"]["subscription"]


class StripeTestInvoiceReader:
    """Build normalized evidence using authoritative GETs, never webhook payloads.

    One simulation only: pin configured invoice/subscription/clock, reject
    partial or unexpectedly large lists, and never follow provider-supplied URLs.
    """

    def __init__(self, test_key: str, run: TestBillingRun, *, opener=None):
        if not isinstance(test_key, str) or not re.fullmatch(r"(?:sk|rk)_test_[A-Za-z0-9_]{8,256}", test_key):
            raise ValueError("a Stripe TEST-only API credential is required")
        if run.rehearsal.sandbox_account_id != FOUNDING_STRIPE_SANDBOX_ACCOUNT:
            raise ValueError("wrong NIJA sandbox")
        self._key = test_key
        self._invoice = _identifier(run.invoice_id, "in_")
        self._subscription = _identifier(run.subscription_id, "sub_")
        self._clock = _identifier(run.test_clock_id, "clock_")
        self._due = run.rehearsal.first_charge_at
        self._opener = opener if opener is not None else build_opener(ProxyHandler({}), _NoRedirect())

    def _get(self, path, **params):
        suffix = "?" + urlencode(params) if params else ""
        request = Request(API + path + suffix, method="GET", headers={
            "Authorization": f"Bearer {self._key}",
            "Stripe-Version": VERSION,
            "Accept": "application/json",
        })
        with self._opener.open(request, timeout=8) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                raise ValueError("Stripe response did not match requested resource")
            raw = response.read(512_001)
            if len(raw) > 512_000:
                raise ValueError("Stripe response exceeds expected bound")
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError("invalid Stripe response")
            return decoded

    def _has_confirmed_test_charge(self, customer):
        """Bind this invoice to one real Stripe TEST tender, not bookkeeping."""
        payments = self._get("/v1/invoice_payments", invoice=self._invoice, status="paid", limit=2)
        if (payments["object"] != "list" or payments["has_more"] is not False
                or not isinstance(payments["data"], list) or len(payments["data"]) != 1):
            return False
        payment = _test_entity(payments["data"][0], "invoice_payment")
        if (payment["invoice"] != self._invoice or payment["status"] != "paid"
                or payment["currency"] != "usd" or _minor(payment["amount_paid"]) != 5000
                or _minor(payment["amount_requested"]) != 5000
                or _timestamp(payment["status_transitions"]["paid_at"]) < self._due
                or payment["payment"]["type"] != "payment_intent"):
            return False
        intent_id = _identifier(payment["payment"]["payment_intent"], "pi_")
        intent = _test_entity(self._get("/v1/payment_intents/" + intent_id),
                              "payment_intent", intent_id)
        if (intent["status"] != "succeeded" or intent["customer"] != customer
                or intent["currency"] != "usd" or _minor(intent["amount_received"]) != 5000):
            return False
        charge_id = _identifier(intent["latest_charge"], "ch_")
        charge = _test_entity(self._get("/v1/charges/" + charge_id), "charge", charge_id)
        return (
            charge["payment_intent"] == intent_id and charge["customer"] == customer
            and charge["currency"] == "usd" and charge["status"] == "succeeded"
            and charge["paid"] is True and charge["captured"] is True
            and _minor(charge["amount_captured"]) == 5000 and _minor(charge["amount_refunded"]) == 0
            and charge["refunded"] is False and charge["disputed"] is False
        )

    def read_invoice(self, invoice_id: str) -> SandboxInvoiceReadback | None:
        if invoice_id != self._invoice:
            return None
        try:
            # Account objects do not expose livemode; the TEST key prefix and
            # each examined resource's explicit livemode field bind the mode.
            account = self._get("/v1/account")
            if account.get("object") != "account" or account.get("id") != FOUNDING_STRIPE_SANDBOX_ACCOUNT:
                return None
            clock = _test_entity(self._get("/v1/test_helpers/test_clocks/" + self._clock),
                                 "test_helpers.test_clock", self._clock)
            if clock["status"] != "ready" or _timestamp(clock["frozen_time"]) < self._due:
                return None
            sub = _test_entity(self._get("/v1/subscriptions/" + self._subscription),
                               "subscription", self._subscription)
            customer = _identifier(sub["customer"], "cus_")
            if sub["test_clock"] != self._clock or _timestamp(sub["trial_end"]) != self._due:
                return None
            invoice = _test_entity(self._get("/v1/invoices/" + self._invoice), "invoice", self._invoice)
            if (invoice["customer"] != customer or invoice["test_clock"] != self._clock
                    or _invoice_subscription(invoice) != self._subscription
                    or invoice["collection_method"] != "charge_automatically"
                    or invoice["billing_reason"] != "subscription_cycle"):
                return None
            lines = invoice["lines"]
            if lines["has_more"] is not False or len(lines["data"]) != 1:
                return None
            line = _test_entity(lines["data"][0], "line_item")
            if (line["parent"]["type"] != "subscription_item_details"
                    or line["parent"]["subscription_item_details"]["subscription"] != self._subscription
                    or line["parent"]["subscription_item_details"]["proration"] is not False
                    or line["pricing"]["type"] != "price_details"
                    or line["currency"] != "usd" or _minor(line["amount"]) != 5000
                    or type(line["quantity"]) is not int or line["quantity"] != 1):
                return None
            # Clock-generated invoices may be excluded from unscoped list
            # queries. Filter by customer AND subscription; fail if incomplete.
            history = self._get("/v1/invoices", customer=customer, subscription=self._subscription, limit=20)
            if (history["object"] != "list" or history["has_more"] is not False
                    or not isinstance(history["data"], list) or len(history["data"]) > 20):
                return None
            positives, seen = [], set()
            for item in history["data"]:
                _test_entity(item, "invoice")
                key = _identifier(item["id"], "in_")
                if (key in seen or item["customer"] != customer
                        or item["test_clock"] != self._clock
                        or _invoice_subscription(item) != self._subscription):
                    return None
                seen.add(key)
                if max(_minor(item["amount_due"]), _minor(item["amount_paid"])) > 0:
                    positives.append(key)
            if positives != [self._invoice] or not self._has_confirmed_test_charge(customer):
                return None
            return SandboxInvoiceReadback(
                account["id"], False, self._clock, self._subscription, invoice["id"],
                (line["pricing"]["price_details"]["price"],), tuple(positives),
                _timestamp(line["period"]["start"]), _timestamp(invoice["status_transitions"]["paid_at"]),
                invoice["status"], invoice["currency"], _minor(invoice["amount_due"]),
                _minor(invoice["amount_paid"]), _minor(invoice["amount_remaining"]),
            )
        except Exception:
            # No raw exception, credentials, URL query or customer data escapes.
            return None


def main(argv=None):
    """Read back an existing, approved isolated simulation; never creates one."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-existing-test-clock", action="store_true", required=True)
    parser.add_argument("--clock-id", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--invoice-id", required=True)
    parser.add_argument("--first-charge-at", required=True, help="Disclosed UTC timestamp, ISO 8601")
    parser.add_argument("--replay-fingerprint", required=True, help="Existing rehearsal fingerprint; not authorization")
    args = parser.parse_args(argv)
    try:
        due = datetime.fromisoformat(args.first_charge_at)
        if due.utcoffset() is None or due.utcoffset().total_seconds() != 0 or due.microsecond:
            raise ValueError("first charge must be a whole-second UTC timestamp")
        if not re.fullmatch(r"[0-9a-f]{64}", args.replay_fingerprint):
            raise ValueError("invalid rehearsal fingerprint")
        run = TestBillingRun(
            SandboxBillingRehearsal(FOUNDING_STRIPE_SANDBOX_ACCOUNT, 5000, due, args.replay_fingerprint),
            args.clock_id, args.subscription_id, args.invoice_id,
        )
        reader = StripeTestInvoiceReader(os.environ.get("NIJA_FOUNDING100_STRIPE_TEST_READ_KEY"), run)
        verified = verify_first_sandbox_invoice(run, reader)
    except (OSError, TypeError, ValueError):
        verified = False
    print(json.dumps({"scope": "isolated_stripe_test_only", "first_invoice_verified": verified}))
    return 0 if verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
