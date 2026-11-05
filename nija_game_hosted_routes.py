"""Isolated first-party hosted checkout: no Vercel secret or cross-domain cookie relay."""
from __future__ import annotations
import os
from nija_game_billing import (
    ALLOWED_ORIGINS, cookie_name, create_checkout, decode_attempt,
    stripe_client, verify_paid_attempt,
)
from nija_game_report_scoring import build_report
from nija_game_report_html import render

def enabled():
    return (os.getenv("NIJA_GAME_BROWSER_CHECKOUT_ENABLED") == "true" and
            os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_live_", "rk_live_")))

def register_hosted_routes(app):
    from flask import Response, jsonify, redirect, request

    @app.after_request
    def hosted_security_headers(response):
        if request.path.startswith("/game/"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            if response.mimetype == "text/html":
                response.headers["Content-Security-Policy"] = (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
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
        if origin not in ALLOWED_ORIGINS:
            return jsonify({"error": "origin_not_allowed"}), 403
        if request.mimetype != "application/x-www-form-urlencoded":
            return jsonify({"error": "form_required"}), 415
        if request.content_length is None or request.content_length > 2048:
            return jsonify({"error": "invalid_form_length"}), 413
        if request.form.get("adult") != "yes":
            return jsonify({"error": "adult_confirmation_required"}), 403
        try:
            decisions = decode_attempt(request.form.get("attempt", ""))
            checkout_url, proof, session_id = create_checkout(
                stripe_client(), decisions, origin, hosted=True)
        except ValueError:
            return jsonify({"error": "invalid_completed_game"}), 422
        except Exception:
            app.logger.exception("NIJA game hosted checkout unavailable")
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
            proof = request.cookies.get(cookie_name(session_id))
            attempt = verify_paid_attempt(stripe_client(), session_id, proof)
            return Response(render(report=build_report(attempt)), mimetype="text/html")
        except ValueError:
            return Response(render(error="A verified purchase and original browser are required."),
                            status=403, mimetype="text/html")
        except Exception:
            app.logger.exception("NIJA paid game report verification unavailable")
            return Response(render(error="We could not verify payment right now. Please retry."),
                            status=503, mimetype="text/html")

    @app.get("/game/cancelled")
    def hosted_game_cancelled():
        return Response(render(error="Checkout was canceled. Your free game remains available."),
                        mimetype="text/html")
