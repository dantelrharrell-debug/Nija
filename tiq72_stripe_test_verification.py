"""TIQ72 Stripe test-mode verification helpers. No routes or live transactions."""
from __future__ import annotations
import os
from urllib.parse import urlsplit

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
        session.get("client_reference_id")!=reservation_id or
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
    key=os.getenv("STRIPE_TEST_SECRET_KEY","")
    if not key.startswith(("sk_test_","rk_test_")):
        raise StripeVerificationError("test_key_required")
    if os.getenv("NIJA_GAME_REPORTS_ENABLED")=="true" or os.getenv("NIJA_GAME_BROWSER_CHECKOUT_ENABLED")=="true":
        raise StripeVerificationError("legacy_payment_flags_must_remain_disabled")
    return True

def _approved_return_url(url: str) -> str:
    """Permit only an explicit HTTPS return origin; never trust a string prefix."""
    approved = os.getenv("TIQ72_TEST_RETURN_ORIGIN", "")
    if not isinstance(url, str) or not isinstance(approved, str):
        raise StripeVerificationError("invalid_checkout_return_url")
    if not (url and approved) or len(url) > 2048 or len(approved) > 255:
        raise StripeVerificationError("approved_return_origin_required")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in url + approved) or "\\" in url + approved:
        raise StripeVerificationError("invalid_checkout_return_url")
    try:
        target = urlsplit(url)
        origin = urlsplit(approved)
        if (origin.scheme != "https" or not origin.hostname or origin.username is not None or
            origin.password is not None or origin.path or origin.query or origin.fragment or
            origin.port not in (None, 443) or
            origin.netloc.lower() != origin.hostname.lower()):
            raise StripeVerificationError("invalid_approved_return_origin")
        if (target.scheme != "https" or target.hostname != origin.hostname or
            target.netloc.lower() != origin.netloc.lower() or
            target.username is not None or target.password is not None or
            target.port not in (None, 443) or target.fragment or
            not target.path.startswith("/")):
            raise StripeVerificationError("invalid_checkout_return_url")
    except ValueError as exc:
        raise StripeVerificationError("invalid_checkout_return_url") from exc
    return url


def create_test_checkout(stripe_client, reservation_id: str, success_url: str, cancel_url: str):
    """Test only; reservation and owner must already be authenticated and stored."""
    assert_test_mode_configuration()
    if (not isinstance(reservation_id, str) or not reservation_id or
        len(reservation_id) > 128 or any(ord(c) < 33 or ord(c) > 126 for c in reservation_id)):
        raise StripeVerificationError("invalid_checkout_parameters")
    safe_success = _approved_return_url(success_url)
    safe_cancel = _approved_return_url(cancel_url)
    price_id, product_id = test_price_identity()
    # Independently verify the configured catalog object before opening Checkout.
    # An environment variable alone is not proof of a $1 sandbox price.
    try:
        price = stripe_client.Price.retrieve(price_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise StripeVerificationError("test_price_retrieval_required") from exc
    if (price.get("id") != price_id or price.get("livemode") is not False or
        price.get("active") is not True or price.get("type") != "one_time" or
        price.get("currency") != "usd" or price.get("unit_amount") != 100 or
        price.get("product") != product_id):
        raise StripeVerificationError("test_price_identity_mismatch")
    return stripe_client.checkout.Session.create(
        mode="payment", line_items=[{"price":price_id,"quantity":1}],
        success_url=safe_success, cancel_url=safe_cancel,
        client_reference_id=reservation_id,
        metadata={"tiq72_reservation_id":reservation_id,"tiq72_version":"v515-72-decisions"},
        idempotency_key="tiq72-test-"+reservation_id,
    )
