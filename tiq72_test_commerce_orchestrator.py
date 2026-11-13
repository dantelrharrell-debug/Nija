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
        # Reject ineligible checkout before persisting any completed-run data.
        if adult_attested is not True:
            raise CommerceDenied("adult_identity_required")
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

    def accept_signed_reversal(self, *, raw_body, signature):
        """Revoke only after matching signed event to a Stripe-retrieved charge.

        This is an isolated test-only method, not an HTTP webhook route.
        """
        assert_test_mode_configuration()
        event = verify_test_webhook(raw_body, signature, self.webhook_secret)
        event_type = event.get("type")
        if event_type not in ("charge.refunded", "charge.dispute.created"):
            raise StripeVerificationError("unsupported_reversal_event")
        obj = event["data"]["object"]
        charge_id = obj.get("id") if event_type == "charge.refunded" else obj.get("charge")
        if not isinstance(charge_id, str) or not charge_id.startswith("ch_"):
            raise StripeVerificationError("charge_identity_required")
        charge = self.stripe.Charge.retrieve(charge_id)
        if charge.get("id") != charge_id or charge.get("livemode") is not False:
            raise StripeVerificationError("test_charge_required")
        if event_type == "charge.refunded":
            if charge.get("refunded") is not True or charge.get("amount_refunded", 0) < 100:
                raise StripeVerificationError("full_refund_not_verified")
        else:
            dispute = self.stripe.Dispute.retrieve(obj.get("id"))
            if (dispute.get("id") != obj.get("id") or
                dispute.get("charge") != charge_id or dispute.get("livemode") is not False):
                raise StripeVerificationError("dispute_not_verified")
        payment_intent = charge.get("payment_intent")
        if not isinstance(payment_intent, str) or not payment_intent.startswith("pi_"):
            raise StripeVerificationError("payment_intent_required")
        rows = self.store.db.execute(
            "SELECT id,stripe_session FROM tiq72_reservations WHERE stripe_session IS NOT NULL"
        ).fetchall()
        matches = []
        for reservation_id, session_id in rows:
            session = self.stripe.checkout.Session.retrieve(session_id, expand=["payment_intent"])
            intent = session.get("payment_intent") or {}
            intent_id = intent if isinstance(intent, str) else intent.get("id")
            if intent_id == payment_intent and session.get("livemode") is False:
                if session.get("client_reference_id") != reservation_id:
                    raise StripeVerificationError("reservation_identity_mismatch")
                matches.append((reservation_id, session_id))
        if len(matches) != 1:
            raise StripeVerificationError("unique_payment_reservation_required")
        reservation_id, session_id = matches[0]
        return self.store.record_verified_event(
            event["id"], event_type, reservation_id, session_id,
            verified_reversal=True)

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
