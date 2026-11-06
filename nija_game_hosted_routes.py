"""Isolated first-party hosted checkout: no Vercel secret or cross-domain cookie relay."""
from __future__ import annotations
import os
import secrets
from html import escape
from typing import Any
from nija_game_checkout_store import CheckoutDenied, CheckoutStore, OWNER_COOKIE, client_identity
from nija_game_billing import (
    ALLOWED_ORIGINS, BILLING_ORIGIN, cookie_name, create_checkout, decode_attempt,
    stripe_client, verify_paid_attempt, validate_attempt, HEX, PUBLIC_ORIGIN,
)
from nija_game_report_scoring import build_report
from nija_game_report_html import render

def enabled() -> bool:
    """Retain the existing explicit live-checkout flag; prerequisites are separately enforced."""
    return (os.getenv("NIJA_GAME_BROWSER_CHECKOUT_ENABLED") == "true" and
            os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_live_", "rk_live_")))

def register_hosted_routes(app: Any) -> None:
    """Register opt-in checkout and independently available paid-report retrieval."""
    from flask import Response, jsonify, redirect, request

    @app.after_request
    def hosted_security_headers(response):
        if request.path.startswith("/game/"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            if response.mimetype == "text/html":
                checkout_form = request.endpoint == "hosted_game_checkout"
                # no-referrer makes form POST Origin opaque in browsers. Keep the
                # strict allowlist below; disclose referrers only within this origin.
                if checkout_form:
                    response.headers["Referrer-Policy"] = "same-origin"
                # CSP applies to the form's redirect chain in some browsers too.
                # Match only the HTTPS Stripe hosts validated by create_checkout.
                form_action = ("'self' https://checkout.stripe.com https://*.checkout.stripe.com"
                               if checkout_form else "'self'")
                response.headers["Content-Security-Policy"] = (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action " + form_action)
        return response

    @app.get("/game/status")
    def hosted_game_status():
        response = jsonify({"checkout_available": enabled(), "free_to_play": True,
                            "price_usd": 1, "billing": "one-time"})
        origin = request.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    @app.post("/game/checkout/start")
    def hosted_game_checkout():
        if not enabled():
            return jsonify({"error": "checkout_unavailable"}), 503
        origin = request.headers.get("Origin", "")
        if origin not in ALLOWED_ORIGINS | {BILLING_ORIGIN}:
            return jsonify({"error": "origin_not_allowed"}), 403
        if request.mimetype != "application/x-www-form-urlencoded":
            return jsonify({"error": "form_required"}), 415
        if request.content_length is None or request.content_length > 2048:
            return jsonify({"error": "invalid_form_length"}), 413
        if request.form.get("adult") != "yes":
            return jsonify({"error": "adult_confirmation_required"}), 403
        try:
            client = client_identity(request)
            store = CheckoutStore(os.getenv("NIJA_GAME_CHECKOUT_DATABASE", ""))
            store.throttle(client)
            decisions = decode_attempt(request.form.get("attempt", ""))
            owner = request.cookies.get(OWNER_COOKIE, "")
            if not HEX.fullmatch(owner):
                # Persist browser ownership BEFORE Stripe. If this response is lost,
                # no chargeable session has been created. Same-site confirmation
                # also works when the initial form came from the external game.
                response = Response(
                    '<!doctype html><meta name="viewport" content="width=device-width">'
                    '<title>NIJA optional results</title><h1>Optional personalized results — $1</h1>'
                    '<p>One-time educational report. Your free game remains available.</p>'
                    '<form method="post" action="/game/checkout/start">'
                    '<input type="hidden" name="adult" value="yes">'
                    '<input type="hidden" name="attempt" value="' + escape(validate_attempt(decisions), quote=True) + '">'
                    '<button>Continue to secure checkout — $1</button></form>', mimetype="text/html")
                response.set_cookie(OWNER_COOKIE, secrets.token_hex(32), max_age=2592000,
                                    secure=True, httponly=True, samesite="None", path="/")
                return response
            reservation = store.reserve(owner, validate_attempt(decisions), BILLING_ORIGIN, client)
            proof = reservation["proof"]
            checkout_url, session_id = reservation["url"], reservation["session"]
            if not checkout_url:
                checkout_url, proof, session_id = create_checkout(
                    stripe_client(), decisions, PUBLIC_ORIGIN, hosted=True, proof=proof,
                    idempotency_key="nija-hosted-v1-" + reservation["id"])
                store.finish(reservation["id"], checkout_url, session_id)
        except CheckoutDenied as error:
            response = jsonify({"error": str(error)})
            response.headers["Retry-After"] = "120"
            return response, error.status
        except ValueError:
            return jsonify({"error": "invalid_completed_game"}), 422
        except Exception:
            app.logger.warning("NIJA game hosted checkout unavailable")
            return jsonify({"error": "checkout_unavailable"}), 503
        response = redirect(checkout_url, code=303)
        response.set_cookie(cookie_name(session_id), proof, max_age=2592000,
                            secure=True, httponly=True, samesite="Lax", path="/")
        return response

    @app.get("/game/results")
    def hosted_game_results():
        # Allow already paid customers to retrieve reports even if checkout is disabled.
        if not os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_live_", "rk_live_")):
            return Response(render(error="Payment verification is unavailable."),
                            status=503, mimetype="text/html")
        session_id = request.args.get("session_id", "")
        try:
            proof = request.cookies.get(cookie_name(session_id)) or request.cookies.get("__Host-nija-report")
            if not isinstance(proof, str) or not HEX.fullmatch(proof):
                raise ValueError("original_browser_required")
            attempt = verify_paid_attempt(stripe_client(), session_id, proof)
            return Response(render(report=build_report(attempt)), mimetype="text/html")
        except ValueError:
            return Response(render(error="A verified purchase and original browser are required."),
                            status=403, mimetype="text/html")
        except Exception:
            app.logger.warning("NIJA paid game report verification unavailable")
            return Response(render(error="We could not verify payment right now. Please retry."),
                            status=503, mimetype="text/html")

    @app.get("/game/cancelled")
    def hosted_game_cancelled():
        return Response(render(error="Checkout was canceled. Your free game remains available."),
                        mimetype="text/html")
