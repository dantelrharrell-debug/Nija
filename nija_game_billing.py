"""One-dollar educational report checkout on NIJA's isolated, existing Render billing service.
Off unless explicitly enabled. Never interacts with broker or live trading modules.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from typing import Any
from urllib.parse import urlparse

LOG = logging.getLogger("nija.game.billing")
PRICE_ID = "price_1UY9YmI0gfJjTf3E1h6mYC2S"
PRODUCT_ID = "prod_VZI9N8jDpFrQMt"
OFFER = "nija-personal-results-v1"
COOKIE = "__Host-nija-report"
PUBLIC_ORIGIN = "https://nija-trading-challenge.vercel.app"
ALLOWED_ORIGINS = frozenset({PUBLIC_ORIGIN, "https://game.nijaaitrading.com"})
SID = re.compile(r"^cs_live_[A-Za-z0-9_]{8,250}$")
HEX = re.compile(r"^[a-f0-9]{64}$")


def field(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def identifier(obj: Any) -> str:
    return obj if isinstance(obj, str) else str(field(obj, "id", "") or "")


def enabled() -> bool:
    token = os.getenv("NIJA_GAME_GATEWAY_TOKEN", "")
    return (os.getenv("NIJA_GAME_REPORTS_ENABLED") == "true" and len(token) >= 48
            and os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_live_", "rk_live_")))


def trusted_gateway(headers: Any) -> bool:
    token = os.getenv("NIJA_GAME_GATEWAY_TOKEN", "")
    provided = headers.get("X-NIJA-Game-Gateway", "") or ""
    return isinstance(provided, str) and len(token) >= 48 and hmac.compare_digest(provided, token)


def validate_attempt(decisions: Any) -> str:
    if not isinstance(decisions, list) or len(decisions) != 5:
        raise ValueError("five_rounds_required")
    parts = []
    for entry in decisions:
        if not isinstance(entry, dict) or entry.get("choice") not in ("long", "short", "wait"):
            raise ValueError("invalid_choice")
        choice = entry["choice"]
        if choice == "wait":
            if "size" in entry or "stop" in entry:
                raise ValueError("wait_must_not_set_risk")
            parts.append("w,0,0")
            continue
        size, stop = entry.get("size"), entry.get("stop")
        if (isinstance(size, bool) or isinstance(stop, bool)
                or not isinstance(size, (int, float)) or not isinstance(stop, (int, float))
                or not (5 <= size <= 50 and (size / 5).is_integer())
                or not (.5 <= stop <= 4 and (stop * 2).is_integer())
                or size * stop / 100 > 1 + 1e-10):
            raise ValueError("risk_limit_or_increment_invalid")
        parts.append(f"{choice[0]},{int(size)},{float(stop):g}")
    result = ";".join(parts)
    if len(result) > 160:
        raise ValueError("invalid_attempt_length")
    return result


def decode_attempt(text: Any) -> list[dict]:
    if not isinstance(text, str) or len(text) > 160:
        raise ValueError("invalid_attempt")
    decisions = []
    for part in text.split(";"):
        parts = part.split(",")
        if len(parts) != 3:
            raise ValueError("invalid_attempt")
        choice = {"l": "long", "s": "short", "w": "wait"}.get(parts[0])
        if not choice:
            raise ValueError("invalid_attempt")
        try:
            size, stop = float(parts[1]), float(parts[2])
        except ValueError as exc:
            raise ValueError("invalid_attempt") from exc
        if choice == "wait":
            if size or stop:
                raise ValueError("invalid_attempt")
            decisions.append({"choice": "wait"})
        else:
            decisions.append({"choice": choice, "size": size, "stop": stop})
    if validate_attempt(decisions) != text:
        raise ValueError("noncanonical_attempt")
    return decisions


def proof_hash(proof: str) -> str:
    return hashlib.sha256(proof.encode("ascii")).hexdigest()


def verify_proof(stored: Any, provided: str) -> bool:
    expected = proof_hash(provided)
    return (isinstance(stored, str) and HEX.fullmatch(stored) is not None
            and hmac.compare_digest(stored, expected))


def stripe_client() -> Any:
    from billing_service import _stripe_module
    return _stripe_module()


def validate_price(stripe: Any) -> None:
    price = stripe.Price.retrieve(PRICE_ID, expand=["product"])
    if not (identifier(price) == PRICE_ID and field(price, "active") is True
            and field(price, "livemode") is True
            and field(price, "type") == "one_time" and field(price, "currency") == "usd"
            and field(price, "unit_amount") == 100
            and identifier(field(price, "product")) == PRODUCT_ID):
        raise RuntimeError("game_price_identity_mismatch")


def create_checkout(stripe: Any, decisions: Any, origin: str) -> tuple[str, str]:
    if origin not in ALLOWED_ORIGINS:
        raise ValueError("untrusted_origin")
    attempt = validate_attempt(decisions)
    validate_price(stripe)
    proof = secrets.token_hex(32)
    checkout = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": PRICE_ID, "quantity": 1}],
        payment_method_types=["card"],
        success_url=origin + "/results.html?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=origin + "/?checkout=cancelled",
        metadata={"nija_offer": OFFER, "nija_product": PRODUCT_ID,
                  "nija_version": "1", "attempt": attempt, "proof_sha256": proof_hash(proof)},
    )
    url = field(checkout, "url", "")
    parsed = urlparse(url)
    if not (parsed.scheme == "https"
            and (parsed.hostname == "checkout.stripe.com"
                 or (parsed.hostname or "").endswith(".checkout.stripe.com"))
            and identifier(checkout) and field(checkout, "mode") == "payment"
            and field(checkout, "livemode") is True):
        raise RuntimeError("unexpected_checkout_response")
    return url, proof


def verify_paid_attempt(stripe: Any, session_id: Any, proof: Any) -> str:
    if not isinstance(session_id, str) or SID.fullmatch(session_id) is None:
        raise ValueError("invalid_session")
    if not isinstance(proof, str) or HEX.fullmatch(proof) is None:
        raise ValueError("original_browser_required")
    checkout = stripe.checkout.Session.retrieve(session_id, expand=["payment_intent.latest_charge"])
    metadata = field(checkout, "metadata") or {}
    if not (identifier(checkout) == session_id and field(checkout, "livemode") is True
            and field(checkout, "mode") == "payment"
            and field(checkout, "status") == "complete"
            and field(checkout, "payment_status") == "paid"
            and field(checkout, "currency") == "usd"
            and field(checkout, "amount_total") == 100
            and field(metadata, "nija_offer") == OFFER
            and field(metadata, "nija_product") == PRODUCT_ID
            and field(metadata, "nija_version") == "1"
            and verify_proof(field(metadata, "proof_sha256"), proof)):
        raise ValueError("purchase_not_verified")
    intent = field(checkout, "payment_intent")
    charge = field(intent, "latest_charge")
    if not (field(intent, "status") == "succeeded"
            and field(intent, "amount_received") == 100
            and field(intent, "currency") == "usd"
            and field(charge, "paid") is True
            and field(charge, "refunded") is not True
            and field(charge, "disputed") is not True
            and not (field(charge, "amount_refunded", 0) or 0)):
        raise ValueError("payment_invalid_or_reversed")
    line_items = field(stripe.checkout.Session.list_line_items(session_id, limit=5), "data", [])
    if (len(line_items) != 1 or field(line_items[0], "quantity") != 1
            or identifier(field(line_items[0], "price")) != PRICE_ID
            or identifier(field(field(line_items[0], "price"), "product")) != PRODUCT_ID):
        raise ValueError("line_item_mismatch")
    attempt = field(metadata, "attempt")
    decode_attempt(attempt)
    return attempt


def register_game_routes(app: Any) -> None:
    """Add isolated game routes; both API and payments fail closed by default."""
    from flask import jsonify, make_response, request

    @app.after_request
    def game_security_headers(response):
        if request.path.startswith("/api/game/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/game/status")
    def game_status():
        return jsonify({"checkout_available": enabled(), "price_usd": 1,
                        "free_to_play": True, "billing": "one-time"})

    @app.post("/api/game/checkout")
    def game_checkout():
        if not enabled():
            return jsonify({"error": "checkout_unavailable"}), 503
        if not trusted_gateway(request.headers):
            return jsonify({"error": "forbidden"}), 403
        if request.headers.get("Origin"):
            return jsonify({"error": "server_to_server_only"}), 403
        if request.content_length and request.content_length > 4096:
            return jsonify({"error": "request_too_large"}), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "invalid_payload"}), 422
        try:
            checkout_url, proof = create_checkout(
                stripe_client(), body.get("decisions"), body.get("origin", PUBLIC_ORIGIN))
        except ValueError:
            return jsonify({"error": "invalid_game_result"}), 422
        except Exception:
            LOG.exception("NIJA game checkout unavailable")
            return jsonify({"error": "payment_service_unavailable"}), 503
        response = make_response(jsonify({"checkout_url": checkout_url}))
        response.set_cookie(COOKIE, proof, max_age=604800, secure=True,
                            httponly=True, samesite="Lax", path="/")
        return response

    @app.get("/api/game/verify")
    def game_verify():
        if not enabled():
            return jsonify({"error": "report_unavailable"}), 503
        if not trusted_gateway(request.headers):
            return jsonify({"error": "forbidden"}), 403
        try:
            attempt = verify_paid_attempt(
                stripe_client(), request.args.get("session_id"), request.cookies.get(COOKIE))
        except ValueError:
            return jsonify({"error": "verified_purchase_required"}), 403
        except Exception:
            LOG.exception("NIJA game report verification unavailable")
            return jsonify({"error": "verification_unavailable"}), 503
        return jsonify({"paid": True, "attempt": attempt})
