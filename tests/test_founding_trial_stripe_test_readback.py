import copy
import io
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from founding_trial_sandbox_receipt import (
    FOUNDING_STRIPE_TEST_PRICE, TestBillingRun as BillingRun, verify_first_sandbox_invoice,
)
from founding_trial_sandbox_workflow import FOUNDING_STRIPE_SANDBOX_ACCOUNT as ACCOUNT, SandboxBillingRehearsal
from founding_trial_stripe_test_readback import StripeTestInvoiceReader, VERSION

DUE = datetime(2026, 11, 15, 10, 30, tzinfo=timezone.utc)
TS = int(DUE.timestamp())
RUN = BillingRun(SandboxBillingRehearsal(ACCOUNT, 5000, DUE, "a" * 64),
                 "clock_fixture", "sub_fixture", "in_fixture")
TEST_KEY = "rk" + "_test_" + "offline_fixture_only"


class Response(io.BytesIO):
    status = 200

    def __init__(self, value, url):
        super().__init__(json.dumps(value).encode())
        self.url = url

    def geturl(self):
        return self.url


@pytest.fixture
def api():
    invoice = {
        "object": "invoice", "livemode": False, "id": RUN.invoice_id,
        "customer": "cus_fixture", "test_clock": RUN.test_clock_id,
        "parent": {"type": "subscription_details", "subscription_details": {
            "subscription": RUN.subscription_id,
        }},
        "billing_reason": "subscription_cycle", "collection_method": "charge_automatically",
        "status": "paid", "currency": "usd", "amount_due": 5000, "amount_paid": 5000,
        "amount_remaining": 0, "status_transitions": {"paid_at": TS + 3700},
        "lines": {"has_more": False, "data": [{
            "object": "line_item", "livemode": False,
            "parent": {"type": "subscription_item_details", "subscription_item_details": {
                "subscription": RUN.subscription_id, "proration": False,
            }},
            "amount": 5000, "currency": "usd", "quantity": 1,
            "pricing": {"type": "price_details", "price_details": {"price": FOUNDING_STRIPE_TEST_PRICE}},
            "period": {"start": TS},
        }]},
    }
    free_trial_invoice = dict(invoice, id="in_trial", amount_due=0, amount_paid=0)
    return {
        "/v1/account": {"object": "account", "id": ACCOUNT},
        "/v1/test_helpers/test_clocks/clock_fixture": {"object": "test_helpers.test_clock",
            "livemode": False, "id": RUN.test_clock_id, "status": "ready", "frozen_time": TS + 4000},
        "/v1/subscriptions/sub_fixture": {"object": "subscription", "livemode": False,
            "id": RUN.subscription_id, "customer": "cus_fixture", "test_clock": RUN.test_clock_id,
            "trial_end": TS},
        "/v1/invoices/in_fixture": invoice,
        "/v1/invoices": {"object": "list", "has_more": False,
            "data": [copy.deepcopy(invoice), free_trial_invoice]},
        "/v1/invoice_payments": {"object": "list", "has_more": False, "data": [{
            "object": "invoice_payment", "livemode": False, "invoice": RUN.invoice_id,
            "status": "paid", "currency": "usd", "amount_paid": 5000, "amount_requested": 5000,
            "status_transitions": {"paid_at": TS + 3700},
            "payment": {"type": "payment_intent", "payment_intent": "pi_fixture"},
        }]},
        "/v1/payment_intents/pi_fixture": {
            "object": "payment_intent", "id": "pi_fixture", "livemode": False,
            "customer": "cus_fixture", "status": "succeeded", "currency": "usd",
            "amount_received": 5000, "latest_charge": "ch_fixture",
        },
        "/v1/charges/ch_fixture": {
            "object": "charge", "id": "ch_fixture", "livemode": False,
            "customer": "cus_fixture", "status": "succeeded", "currency": "usd",
            "paid": True, "captured": True, "amount_captured": 5000, "amount_refunded": 0,
            "refunded": False, "disputed": False, "payment_intent": "pi_fixture",
        },
    }


class Opener:
    def __init__(self, api):
        self.api = api
        self.paths = []

    def open(self, request, *, timeout):
        url = urlsplit(request.full_url)
        assert url.scheme == "https" and url.netloc == "api.stripe.com"
        assert request.get_method() == "GET" and timeout == 8
        assert request.get_header("Stripe-version") == VERSION
        assert request.get_header("Authorization") == "Bearer " + TEST_KEY
        if url.path == "/v1/invoices":
            assert parse_qs(url.query) == {
                "customer": ["cus_fixture"], "subscription": [RUN.subscription_id], "limit": ["20"],
            }
        elif url.path == "/v1/invoice_payments":
            assert parse_qs(url.query) == {"invoice": [RUN.invoice_id], "status": ["paid"], "limit": ["2"]}
        else:
            assert not url.query
        self.paths.append(url.path)
        return Response(self.api[url.path], request.full_url)


def test_stripe_shaped_snapshot_through_actual_get_readback_and_merged_gate(api):
    opener = Opener(api)
    reader = StripeTestInvoiceReader(TEST_KEY, RUN, opener=opener)
    assert verify_first_sandbox_invoice(RUN, reader)
    assert opener.paths == list(api)


@pytest.mark.parametrize("key", [None, "sk" + "_live_" + "not_secret", "pk_test_value", "rk_test_invalid space"])
def test_key_mode_denied_before_any_access(api, key):
    opener = Opener(api)
    with pytest.raises(ValueError):
        StripeTestInvoiceReader(key, RUN, opener=opener)
    assert not opener.paths


def test_account_mismatch_stops_before_any_receipt_read(api):
    api["/v1/account"]["id"] = "acct_wrong"
    opener = Opener(api)
    reader = StripeTestInvoiceReader(TEST_KEY, RUN, opener=opener)
    assert not verify_first_sandbox_invoice(RUN, reader)
    assert opener.paths == ["/v1/account"]


@pytest.mark.parametrize("path,changes", [
    ("/v1/test_helpers/test_clocks/clock_fixture", {"status": "advancing"}),
    ("/v1/test_helpers/test_clocks/clock_fixture", {"frozen_time": TS - 1}),
    ("/v1/subscriptions/sub_fixture", {"trial_end": TS - 1}),
    ("/v1/subscriptions/sub_fixture", {"livemode": True}),
    ("/v1/invoices/in_fixture", {"customer": "cus_wrong"}),
    ("/v1/invoices/in_fixture", {"billing_reason": "manual"}),
    ("/v1/invoices/in_fixture", {"collection_method": "send_invoice"}),
    ("/v1/invoices/in_fixture", {"lines": {"data": [], "has_more": True}}),
    ("/v1/invoices", {"has_more": True}),
])
def test_incomplete_or_unrelated_provider_data_cannot_certify(api, path, changes):
    api[path].update(changes)
    assert not verify_first_sandbox_invoice(RUN, StripeTestInvoiceReader(TEST_KEY, RUN, opener=Opener(api)))


def test_competing_positive_invoice_denied(api):
    prior = dict(api["/v1/invoices"]["data"][0], id="in_prior")
    api["/v1/invoices"]["data"].append(prior)
    assert not verify_first_sandbox_invoice(RUN, StripeTestInvoiceReader(TEST_KEY, RUN, opener=Opener(api)))


def test_cli_without_key_reports_only_value_free_failure(monkeypatch, capsys):
    from founding_trial_stripe_test_readback import main

    monkeypatch.delenv("NIJA_FOUNDING100_STRIPE_TEST_READ_KEY", raising=False)
    assert main([
        "--verify-existing-test-clock", "--clock-id", RUN.test_clock_id,
        "--subscription-id", RUN.subscription_id, "--invoice-id", RUN.invoice_id,
        "--first-charge-at", DUE.isoformat(), "--replay-fingerprint", "a" * 64,
    ]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "scope": "isolated_stripe_test_only", "first_invoice_verified": False,
    }


def test_paid_status_without_stripe_payment_is_not_provider_proof(api):
    api["/v1/invoice_payments"] = {"object": "list", "has_more": False, "data": []}
    assert not verify_first_sandbox_invoice(RUN, StripeTestInvoiceReader(TEST_KEY, RUN, opener=Opener(api)))


@pytest.mark.parametrize("path,changes", [
    ("/v1/invoice_payments", {"has_more": True}),
    ("/v1/payment_intents/pi_fixture", {"livemode": True}),
    ("/v1/payment_intents/pi_fixture", {"customer": "cus_wrong"}),
    ("/v1/payment_intents/pi_fixture", {"status": "requires_payment_method"}),
    ("/v1/payment_intents/pi_fixture", {"amount_received": 4999}),
    ("/v1/charges/ch_fixture", {"payment_intent": "pi_wrong"}),
    ("/v1/charges/ch_fixture", {"amount_refunded": 1}),
    ("/v1/charges/ch_fixture", {"disputed": True}),
    ("/v1/charges/ch_fixture", {"captured": False}),
])
def test_incomplete_unrelated_or_reversed_tender_cannot_certify(api, path, changes):
    api[path].update(changes)
    assert not verify_first_sandbox_invoice(RUN, StripeTestInvoiceReader(TEST_KEY, RUN, opener=Opener(api)))


def test_paid_outside_provider_or_duplicate_tenders_cannot_certify(api):
    payments = api["/v1/invoice_payments"]["data"]
    payments.append(copy.deepcopy(payments[0]))
    assert not verify_first_sandbox_invoice(RUN, StripeTestInvoiceReader(TEST_KEY, RUN, opener=Opener(api)))
    payments.pop()
    payments[0]["payment"] = {"type": "payment_record", "payment_record": "synthetic"}
    assert not verify_first_sandbox_invoice(RUN, StripeTestInvoiceReader(TEST_KEY, RUN, opener=Opener(api)))
