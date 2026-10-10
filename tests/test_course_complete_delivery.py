"""Isolated Stripe webhook -> verified entitlement -> Resend -> private access test.

No Stripe charges, Resend messages, Render database writes or trading APIs.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from sqlalchemy import select

import billing_service as billing
import course_portal as portal
from billing_service_store import BillingServiceStore
from course_fulfillment import COURSE_LINK, COURSE_PRICE, COURSE_PRODUCT


def test_signed_course_checkout_sends_single_claim_and_revokes_on_refund(monkeypatch, tmp_path):
    monkeypatch.setenv("NIJA_BILLING_IDENTITY_SECRET", "test-identity-secret")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_not_real")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_only")
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("NIJA_COURSE_SESSION_SECRET", "test-course-signing-secret-" * 3)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_not_real")

    store = BillingServiceStore(f"sqlite:///{tmp_path / 'billing.db'}")
    app = billing.create_app(store)
    client = app.test_client()
    course_store = app.config["COURSE_PORTAL_STORE"]
    monkeypatch.setattr(course_store, "has_bundle", lambda: True)
    monkeypatch.setattr(
        course_store, "asset_bytes",
        lambda filename: b"%PDF-1.4\nPrivate purchased copy" if filename.endswith(".pdf")
        else b"ID3private-audio" if filename.endswith(".mp3") else None,
    )

    session_id = "cs_test_foundations_paid"
    state = {"refunded": False, "paid": True}
    outbound = []

    def session(_sid, **_kwargs):
        assert _sid == session_id
        return {
            "id": session_id,
            "payment_link": COURSE_LINK,
            "mode": "payment",
            "status": "complete" if state["paid"] else "open",
            "payment_status": "paid" if state["paid"] else "unpaid",
            "customer_details": {"email": "buyer@example.test"},
            "customer": "cus_test_foundations",
            "payment_intent": "pi_test_foundations",
            "amount_subtotal": 9900,
            "amount_total": 9900,
            "total_details": {"amount_tax": 0, "amount_discount": 0},
        }

    def signed_event(raw_payload, signature, signing_secret):
        assert signing_secret == "whsec_test_only"
        if signature != "valid-test-signature":
            raise ValueError("invalid signed event")
        assert raw_payload == b"synthetic-signed-event"
        return {
            "id": "evt_test_foundations_paid",
            "type": "checkout.session.completed",
            "created": 1780000000,
            "data": {"object": {"id": session_id, "payment_link": COURSE_LINK}},
        }

    stripe = SimpleNamespace(
        checkout=SimpleNamespace(
            Session=SimpleNamespace(
                retrieve=session,
                list_line_items=lambda sid, **_kwargs: {
                    "data": [{"quantity": 1, "price": {
                        "id": COURSE_PRICE, "product": COURSE_PRODUCT,
                        "unit_amount": 9900, "currency": "usd",
                    }}],
                    "has_more": False,
                },
            ),
        ),
        PaymentIntent=SimpleNamespace(retrieve=lambda _sid: {
            "status": "succeeded", "amount_received": 9900,
            "currency": "usd", "latest_charge": "ch_test_foundations",
        }),
        Charge=SimpleNamespace(retrieve=lambda _sid: {
            "paid": True, "status": "succeeded", "currency": "usd",
            "amount": 9900, "payment_intent": "pi_test_foundations",
            "refunded": state["refunded"],
            "amount_refunded": 9900 if state["refunded"] else 0,
            "disputed": False,
        }),
        Webhook=SimpleNamespace(construct_event=signed_event),
        error=SimpleNamespace(SignatureVerificationError=ValueError),
    )
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    monkeypatch.setattr(portal, "_stripe", lambda: stripe)

    def send_email(url, *, json, headers, timeout):
        assert url == "https://api.resend.com/emails"
        assert timeout == 5
        assert headers["Idempotency-Key"] == "nija-foundations-delivery-v1-" + session_id
        assert json["to"] == ["buyer@example.test"]
        assert "/course-portal/claim?token=" in json["html"]
        outbound.append(json)
        return SimpleNamespace(status_code=201, json=lambda: {"id": "email_mock_1"})

    monkeypatch.setattr(portal.requests, "post", send_email)

    # Invalid signatures must never grant an entitlement or send a message.
    assert client.post("/api/billing/webhook", data=b"synthetic-signed-event",
                       headers={"Stripe-Signature": "invalid"}).status_code == 400
    assert outbound == []

    # The parent webhook must verify payment and charge before triggering email.
    response = client.post("/api/billing/webhook", data=b"synthetic-signed-event",
                           headers={"Stripe-Signature": "valid-test-signature"})
    assert response.status_code == 200, response.get_json()
    assert app.config["COURSE_LEDGER"].get(session_id)["granted"] is True
    with course_store.engine.connect() as conn:
        status = conn.execute(select(course_store.outbox.c.status).where(
            course_store.outbox.c.session_id == session_id)).scalar_one()
    assert status == "sent"
    assert len(outbound) == 1

    # Retries of the webhook or success page must not trigger duplicate email.
    duplicate = client.post("/api/billing/webhook", data=b"synthetic-signed-event",
                            headers={"Stripe-Signature": "valid-test-signature"})
    assert duplicate.status_code == 200 and duplicate.get_json()["duplicate"] is True
    thank_you = client.get(
        "/course-portal/thank-you?session_id=" + session_id,
        base_url="https://localhost",
    )
    assert b"Payment Verified" in thank_you.data
    assert len(outbound) == 1

    # Access can only be activated with the unique email-delivered claim link.
    claim_token = re.search(r"/course-portal/claim\?token=([^\"< ]+)", outbound[0]["html"]).group(1)
    accepted = client.get("/course-portal/claim?token=" + claim_token,
                          base_url="https://localhost")
    assert accepted.status_code == 303
    assert client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf",
                      base_url="https://localhost").status_code == 200
    assert client.get("/course-portal/file/NIJA_AI_Trading_Foundations_Final_Audiobook_Under_50MB.mp3",
                      base_url="https://localhost").status_code == 200
    assert client.get("/course-portal/claim?token=" + claim_token,
                      base_url="https://localhost").status_code == 403

    # Refund verification revokes access without changing NIJA subscriptions.
    state["refunded"] = True
    assert client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf",
                      base_url="https://localhost").status_code == 403
    assert app.config["COURSE_LEDGER"].get(session_id)["granted"] is False
    assert len(outbound) == 1
