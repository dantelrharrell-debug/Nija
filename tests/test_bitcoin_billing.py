"""Contract tests for NIJA's fail-closed Bitcoin payment rail."""
from __future__ import annotations

from types import SimpleNamespace

from flask import Flask

from billing_service_store import BillingServiceStore
from bitcoin_billing import register_bitcoin_routes


class FakeBitPay:
    def __init__(self):
        self.created = None
        self.invoice = None

    def create_invoice(self, **kwargs):
        self.created = kwargs
        return {
            "id": "bitpay_inv_1",
            "url": "https://bitpay.test/invoice/bitpay_inv_1",
            "orderId": kwargs["order_id"],
            "status": "new",
        }

    def retrieve_invoice(self, invoice_id):
        assert invoice_id == "bitpay_inv_1"
        return self.invoice


def _app(monkeypatch, tmp_path, *, offer_code="lessons"):
    monkeypatch.setenv("NIJA_BITCOIN_PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("NIJA_BITCOIN_ENABLED_OFFERS", "lessons,founding_beta")
    monkeypatch.setenv("NIJA_BITCOIN_ALLOW_RECURRING_ONE_TIME_PAYMENTS", "false")
    monkeypatch.setenv("NIJA_BILLING_PUBLIC_URL", "https://billing.example.test")
    store = BillingServiceStore(f"sqlite:///{tmp_path / 'billing.db'}")
    fake = FakeBitPay()
    app = Flask(__name__)
    identity = SimpleNamespace(
        user_id="application-123",
        email="member@example.test",
        offer_code=offer_code,
    )
    register_bitcoin_routes(
        app,
        store_getter=lambda: store,
        identity_loader=lambda: identity,
        identity_error_types=(ValueError,),
        site_url=lambda: "https://nijaaitrading.com",
        client_factory=lambda: fake,
    )
    return app, store, fake


def test_bitcoin_checkout_is_server_priced_and_does_not_grant_entitlement(monkeypatch, tmp_path):
    app, store, fake = _app(monkeypatch, tmp_path)

    response = app.test_client().post("/api/billing/bitcoin/checkout")
    assert response.status_code == 200
    body = response.get_json()
    assert body["payment_method"] == "bitcoin"
    assert body["invoice_id"] == "bitpay_inv_1"
    assert body["payment_verified"] is False
    assert body["entitlement_granted"] is False
    assert body["brokerage_sweep_allowed"] is False

    assert fake.created["amount_usd"].quantize(1) == 99
    assert fake.created["notification_url"] == (
        "https://billing.example.test/api/billing/bitcoin/webhook"
    )
    assert fake.created["redirect_url"] == "https://nijaaitrading.com/bitcoin-success"

    record = store.get_bitcoin_order_by_invoice("bitpay_inv_1")
    assert record["offer_code"] == "lessons"
    assert record["amount_usd_cents"] == 9900
    assert record["verified"] is False
    assert record["treasury_status"] == "hold"


def test_recurring_offer_is_rejected_until_manual_renewal_policy_is_enabled(monkeypatch, tmp_path):
    app, _store, fake = _app(monkeypatch, tmp_path, offer_code="founding_beta")

    response = app.test_client().post("/api/billing/bitcoin/checkout")
    assert response.status_code == 409
    assert response.get_json()["error"] == "bitcoin_recurring_offer_not_enabled"
    assert fake.created is None


def test_ipn_payload_is_never_payment_authority(monkeypatch, tmp_path):
    app, _store, fake = _app(monkeypatch, tmp_path)
    client = app.test_client()
    create = client.post("/api/billing/bitcoin/checkout")
    order_id = fake.created["order_id"]

    # The untrusted callback lies and says complete. The authoritative provider
    # retrieval still says paid, so NIJA must remain pending.
    fake.invoice = {
        "id": "bitpay_inv_1",
        "orderId": order_id,
        "price": "99.00",
        "currency": "USD",
        "status": "paid",
        "paymentSubtotals": {"BTC": 150000},
    }
    response = client.post(
        "/api/billing/bitcoin/webhook",
        json={"id": "bitpay_inv_1", "status": "complete", "price": 1},
    )
    assert response.status_code == 200
    verify = client.get("/api/billing/bitcoin/verify?invoice_id=bitpay_inv_1").get_json()
    assert verify["state"] == "pending"
    assert verify["payment_verified"] is False
    assert verify["brokerage_sweep_allowed"] is False

    # Only the authenticated retrieval can advance the payment.
    fake.invoice["status"] = "complete"
    response = client.post("/api/billing/bitcoin/webhook", json={"id": "bitpay_inv_1"})
    assert response.status_code == 200
    verify = client.get("/api/billing/bitcoin/verify?invoice_id=bitpay_inv_1").get_json()
    assert verify["state"] == "verified"
    assert verify["payment_verified"] is True
    assert verify["treasury_status"] == "provider_complete"
    assert verify["entitlement_granted"] is False
    assert verify["brokerage_sweep_allowed"] is False
    assert verify["btc_paid_satoshis"] == 150000


def test_authoritative_price_or_order_mismatch_fails_closed(monkeypatch, tmp_path):
    app, _store, fake = _app(monkeypatch, tmp_path)
    client = app.test_client()
    client.post("/api/billing/bitcoin/checkout")

    fake.invoice = {
        "id": "bitpay_inv_1",
        "orderId": "not-the-nija-order",
        "price": "99.00",
        "currency": "USD",
        "status": "complete",
    }
    response = client.post("/api/billing/bitcoin/webhook", json={"id": "bitpay_inv_1"})
    assert response.status_code == 200

    verify = client.get("/api/billing/bitcoin/verify?invoice_id=bitpay_inv_1").get_json()
    assert verify["state"] == "failed"
    assert verify["payment_verified"] is False
    assert verify["treasury_status"] == "hold"
    assert verify["brokerage_sweep_allowed"] is False
