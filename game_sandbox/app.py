"""HTTP and Stripe adapters for the separate sandbox process only."""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from .service import COOKIE, Config, Denied, Manifest, Sandbox, digest


class StripeGateway:
    """Use an instance-scoped SDK client; never set Stripe global credentials."""

    def __init__(self, key: str):
        if not key.startswith(("rk_test_", "sk_test_")):
            raise Denied("test_key_required")
        import stripe

        self.client = stripe.StripeClient(key, stripe_version="2026-09-30.endive", max_network_retries=2)

    def price(self, price_id: str) -> dict:
        """Retrieve the configured sandbox price."""
        return self.client.v1.prices.retrieve(price_id).to_dict()

    def create(self, params: dict, idempotency_key: str) -> dict:
        """Create one hosted Checkout, retaining a stable per-run idempotency key."""
        params = dict(
            params,
            integration_identifier="nija_iq_sandbox_"
            + "".join(chr(97 + int(c, 16)) for c in digest(idempotency_key)[:8]),
        )
        return self.client.v1.checkout.sessions.create(
            params=params, options={"idempotency_key": idempotency_key}
        ).to_dict()

    def purchase(self, session_id: str) -> tuple[dict, dict]:
        """Expand charge state and retrieve the exact line item."""
        sessions = self.client.v1.checkout.sessions
        session = sessions.retrieve(session_id, params={"expand": ["payment_intent.latest_charge"]})
        lines = sessions.list_line_items(session_id, params={"limit": 2})
        return session.to_dict(), lines.to_dict()

    def event(self, raw: bytes, signature: str, secret: str) -> dict:
        """Reject forged, tampered or expired deliveries using the official SDK."""
        import stripe

        try:
            return self.client.construct_event(raw, signature, secret, tolerance=300).to_dict()
        except stripe.SignatureVerificationError as error:
            raise Denied("invalid_webhook_signature") from error


def create_app(service: Sandbox) -> Any:
    """Create a same-origin API. No CORS grants or production route registration."""
    from flask import Flask, jsonify, request

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 65536

    @app.before_request
    def protect() -> Any:
        if request.path == "/sandbox/stripe/webhook":
            return None
        if request.method != "GET" and request.headers.get("Origin") != service.config.origin:
            return jsonify(error="origin_required"), 403
        if request.method != "GET" and request.mimetype != "application/json":
            return jsonify(error="json_required"), 415
        # Dedicated ingress must additionally rate-limit by verified client IP.
        bucket = digest(request.remote_addr or "unknown")
        now = int(time.time())
        with service.db() as db:
            row = db.execute("SELECT * FROM limits WHERE owner_hash=?", (bucket,)).fetchone()
            count = row["count"] + 1 if row and now - row["started"] < 3600 else 1
            started = row["started"] if row and now - row["started"] < 3600 else now
            if count > 300:
                return jsonify(error="rate_limited"), 429
            db.execute("INSERT OR REPLACE INTO limits VALUES (?,?,?)", (bucket, started, count))
        return None

    @app.after_request
    def headers(response: Any) -> Any:
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            }
        )
        return response

    @app.errorhandler(Denied)
    def denied(error: Denied) -> Any:
        return jsonify(error=str(error)), 403

    @app.errorhandler(Exception)
    def unavailable(error: Exception) -> Any:
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return jsonify(error="invalid_request"), error.code
        # Provider exceptions can include sensitive requests; do not log exception payloads.
        app.logger.warning("Sandbox request failed: %s", type(error).__name__)
        return jsonify(error="sandbox_service_unavailable"), 503

    def receipt() -> str:
        values = request.cookies.getlist(COOKIE)
        if len(values) != 1:
            raise Denied("ownership_required")
        return values[0]

    def csrf() -> str:
        value = request.headers.get("X-NIJA-CSRF", "")
        if not value:
            raise Denied("csrf_required")
        return value

    @app.get("/sandbox/health")
    def health() -> Any:
        return jsonify(sandbox=True, live_payments=False, manifest=service.manifest.digest)

    @app.post("/sandbox/runs")
    def start() -> Any:
        body = request.get_json()
        if not isinstance(body, dict) or set(body) != {"adultConfirmed"}:
            raise Denied("invalid_request")
        owner = request.cookies.get(COOKIE)
        run_id, owner, token = service.start(body["adultConfirmed"], owner)
        response = jsonify(run_id=run_id, csrf=token)
        response.set_cookie(COOKIE, owner, secure=True, httponly=True, samesite="Lax", max_age=365 * 86400, path="/")
        return response

    @app.post("/sandbox/runs/<run_id>/resume")
    def resume(run_id: str) -> Any:
        # Same-origin read; issue CSRF to an authenticated owner on page refresh.
        token = secrets.token_hex(32)
        with service.db() as db:
            service.owned(db, run_id, receipt())
            db.execute("UPDATE runs SET csrf_hash=? WHERE id=?", (digest(token), run_id))
        return jsonify(run_id=run_id, csrf=token)

    @app.post("/sandbox/runs/<run_id>/complete")
    def complete(run_id: str) -> Any:
        body = request.get_json()
        if not isinstance(body, dict) or set(body) != {"answers"}:
            raise Denied("invalid_request")
        service.complete(run_id, receipt(), csrf(), body["answers"])
        return jsonify(completed=True)

    @app.post("/sandbox/runs/<run_id>/checkout")
    def checkout(run_id: str) -> Any:
        return jsonify(service.checkout(run_id, receipt(), csrf()))

    @app.get("/sandbox/runs/<run_id>/report")
    def report(run_id: str) -> Any:
        return jsonify(report=service.report(run_id, receipt()))

    @app.post("/sandbox/stripe/webhook")
    def webhook() -> Any:
        try:
            service.webhook(request.get_data(cache=False), request.headers.get("Stripe-Signature", ""))
        except (ValueError, KeyError, TypeError):
            return jsonify(error="invalid_or_unbound_webhook"), 400
        return jsonify(received=True)

    return app


def from_environment() -> Any:
    """Require pinned canonical source and original server-side report adapter."""
    config = Config(
        database=os.environ["NIJA_IQ_SANDBOX_DATABASE"],
        origin=os.environ["NIJA_IQ_SANDBOX_ORIGIN"],
        key=os.environ["NIJA_IQ_SANDBOX_STRIPE_KEY"],
        webhook_secret=os.environ["NIJA_IQ_SANDBOX_WEBHOOK_SECRET"],
        price=os.environ["NIJA_IQ_SANDBOX_PRICE_ID"],
        product=os.environ["NIJA_IQ_SANDBOX_PRODUCT_ID"],
        enabled=os.environ.get("NIJA_IQ_SANDBOX_ENABLED") == "true",
    )
    config.validate()
    manifest = Manifest(json.loads(Path(os.environ["NIJA_IQ_SANDBOX_MANIFEST"]).read_text()))
    if manifest.digest != os.environ.get("NIJA_IQ_SANDBOX_MANIFEST_SHA256"):
        raise Denied("reviewed_manifest_pin_required")
    adapter = Path(os.environ["NIJA_IQ_SANDBOX_REPORT_ADAPTER"])
    if digest(adapter.read_text()) != os.environ.get("NIJA_IQ_SANDBOX_REPORT_ADAPTER_SHA256"):
        raise Denied("reviewed_original_report_adapter_required")
    spec = importlib.util.spec_from_file_location("private_iq_report", adapter)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return create_app(Sandbox(config, manifest, StripeGateway(config.key), module.build_report))
