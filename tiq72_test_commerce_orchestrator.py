"""Review-only TIQ72 test-commerce orchestration; never register as a production route.

Callers must authenticate owner_id and provide an authoritative, server-scored run.
Webhook callers must supply the unmodified Stripe request bytes and signature.
"""
from __future__ import annotations
from tiq72_commerce_store import CommerceDenied
from tiq72_stripe_test_verification import (
    assert_test_mode_configuration, create_test_checkout,
    verify_test_checkout, verify_test_webhook, StripeVerificationError,
)

class Tiq72TestCommerce:
    def __init__(self, store, stripe_client, webhook_secret):
        self.store = store
        self.stripe = stripe_client
        self.webhook_secret = webhook_secret

    def start_checkout(self, *, owner_id, adult_attested, canonical_run,
                       authoritative_score, success_url, cancel_url):
        """Caller must verify identity and obtain score from the trusted engine."""
        assert_test_mode_configuration()
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise CommerceDenied("authenticated_owner_required")
        run_id = self.store.save_run(owner_id, "v515-72-decisions",
                                     canonical_run, authoritative_score)
        reservation_id = self.store.reserve(run_id, owner_id, adult_attested)
        session = create_test_checkout(self.stripe, reservation_id,
                                       success_url, cancel_url)
        if session.get("livemode") is not False or not str(session.get("id","")).startswith("cs_test_"):
            raise StripeVerificationError("test_session_required")
        self.store.attach_session(reservation_id, session["id"])
        return {"reservation_id": reservation_id, "checkout_url": session["url"]}

    def accept_signed_checkout(self, *, raw_body, signature):
        """Grant only after signature verification and independent Stripe retrieval."""
        assert_test_mode_configuration()
        event = verify_test_webhook(raw_body, signature, self.webhook_secret)
        if event.get("type") not in (
            "checkout.session.completed", "checkout.session.async_payment_succeeded"
        ):
            raise StripeVerificationError("unsupported_checkout_event")
        obj = event["data"]["object"]
        session_id = obj.get("id")
        reservation_id = (obj.get("metadata") or {}).get("tiq72_reservation_id")
        if not isinstance(reservation_id, str) or not reservation_id:
            raise StripeVerificationError("reservation_missing")
        verify_test_checkout(self.stripe, session_id, reservation_id)
        return self.store.record_verified_event(
            event["id"], event["type"], reservation_id, session_id,
            verified_paid=True)

    def fulfill_report(self, *, owner_id, reservation_id, report):
        """Report must be generated server-side; never accept a browser-authored report."""
        if not isinstance(owner_id, str) or not owner_id:
            raise CommerceDenied("authenticated_owner_required")
        row = self.store.db.execute(
            "SELECT owner_id FROM tiq72_reservations WHERE id=?",
            (reservation_id,)).fetchone()
        if not row or row[0] != owner_id:
            raise CommerceDenied("reservation_not_owned")
        self.store.save_report(reservation_id, report)
        return self.store.get_report(reservation_id, owner_id)
