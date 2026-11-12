"""TIQ72 Stripe test-mode verification helpers. No routes or live transactions."""
from __future__ import annotations
import os

def test_price_identity():
    price = os.getenv("TIQ72_STRIPE_TEST_PRICE_ID", "").strip()
    product = os.getenv("TIQ72_STRIPE_TEST_PRODUCT_ID", "").strip()
    if not price.startswith("price_") or not product.startswith("prod_"):
        raise StripeVerificationError("test_price_configuration_required")
    return price, product


class StripeVerificationError(ValueError):
    pass

def verify_test_webhook(raw_body: bytes, signature: str, secret: str):
    """Verify the unmodified request body before parsing any event."""
    if not isinstance(raw_body, bytes) or not raw_body or len(raw_body)>65536:
        raise StripeVerificationError("invalid_webhook_body")
    if not signature or not secret or not secret.startswith("whsec_"):
        raise StripeVerificationError("webhook_signature_required")
    import stripe
    try:
        event = stripe.Webhook.construct_event(raw_body, signature, secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise StripeVerificationError("invalid_webhook_signature") from exc
    if event.get("livemode") is not False or not str(event.get("id","")).startswith("evt_"):
        raise StripeVerificationError("test_event_required")
    return event

def verify_test_checkout(stripe_client, session_id: str, reservation_id: str):
    """Server-side reconciliation. Do not trust webhook metadata as payment proof."""
    if not isinstance(session_id,str) or not session_id.startswith("cs_test_"):
        raise StripeVerificationError("test_session_required")
    session = stripe_client.checkout.Session.retrieve(session_id,expand=["payment_intent"])
    if (session.get("id")!=session_id or session.get("livemode") is not False or
        session.get("mode")!="payment" or session.get("payment_status")!="paid" or
        session.get("status")!="complete" or session.get("currency")!="usd" or
        session.get("amount_total")!=100 or
        session.get("metadata",{}).get("tiq72_reservation_id")!=reservation_id or
        session.get("metadata",{}).get("tiq72_version")!="v515-72-decisions"):
        raise StripeVerificationError("checkout_identity_mismatch")
    intent=session.get("payment_intent") or {}
    if intent.get("status")!="succeeded" or intent.get("amount_received")!=100:
        raise StripeVerificationError("payment_intent_unpaid")
    items=stripe_client.checkout.Session.list_line_items(session_id,limit=3).get("data",[])
    if len(items)!=1 or items[0].get("quantity")!=1:
        raise StripeVerificationError("line_item_mismatch")
    price=items[0].get("price") or {}
    product=price.get("product")
    product_id=product if isinstance(product,str) else (product or {}).get("id")
    expected_price, expected_product = test_price_identity()
    if price.get("id")!=expected_price or product_id!=expected_product:
        raise StripeVerificationError("wrong_product")
    return session

def assert_test_mode_configuration():
    key=os.getenv("STRIPE_SECRET_KEY","")
    if not key.startswith(("sk_test_","rk_test_")):
        raise StripeVerificationError("test_key_required")
    if os.getenv("NIJA_GAME_REPORTS_ENABLED")=="true" or os.getenv("NIJA_GAME_BROWSER_CHECKOUT_ENABLED")=="true":
        raise StripeVerificationError("legacy_payment_flags_must_remain_disabled")
    return True

def create_test_checkout(stripe_client, reservation_id: str, success_url: str, cancel_url: str):
    """Test-mode only. Reservation must already be authenticated and persisted."""
    assert_test_mode_configuration()
    if not reservation_id or not all(isinstance(url,str) and url.startswith("https://") for url in (success_url,cancel_url)):
        raise StripeVerificationError("invalid_checkout_parameters")
    price_id, _ = test_price_identity()
    return stripe_client.checkout.Session.create(
        mode="payment", line_items=[{"price":price_id,"quantity":1}],
        success_url=success_url, cancel_url=cancel_url,
        client_reference_id=reservation_id,
        metadata={"tiq72_reservation_id":reservation_id,"tiq72_version":"v515-72-decisions"},
        idempotency_key="tiq72-test-"+reservation_id,
    )
