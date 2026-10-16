"""Server-to-server Founding 100 lifecycle and mail operations; no billing mutations."""
from __future__ import annotations

import os
import sqlite3
import time

import click
import jwt
from flask import Blueprint, jsonify, request

from founding_onboarding_mail import InvitationOutbox, normalize_email, verify_resend_event


def _assertion(audience: str, secret_name: str, *, required=()) -> dict:
    secret = os.getenv(secret_name, "").strip()
    if not secret:
        raise RuntimeError("onboarding_identity_not_configured")
    parts = request.headers.get("Authorization", "").split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("identity_assertion_required")
    try:
        claims = jwt.decode(
            parts[1], secret, algorithms=["HS256"], audience=audience, issuer="nija-identity",
            options={"require": ["sub", "exp", "iat", *required]},
        )
        if (not isinstance(claims["sub"], str) or not claims["sub"]
                or claims["exp"] - claims["iat"] > 300):
            raise ValueError("short_lived_identity_required")
        return claims
    except (jwt.PyJWTError, TypeError) as exc:
        raise ValueError("identity_assertion_invalid") from exc


def register_onboarding_routes(app, billing_store) -> None:
    """Register a volume-backed outbox only when its absolute durable path is configured."""
    path = os.getenv("NIJA_ONBOARDING_DB_PATH", "").strip()
    if not path:
        return
    if not os.path.isabs(path) or path == ":memory:":
        raise RuntimeError("onboarding_requires_absolute_durable_db_path")
    outbox = InvitationOutbox(path)
    app.config["ONBOARDING_OUTBOX"] = outbox
    routes = Blueprint("founding_onboarding", __name__)

    @routes.before_request
    def guard_request():
        if request.content_length is None and request.method == "POST":
            return jsonify({"error": "content_length_required"}), 411
        if (request.content_length or 0) > 65536:
            return jsonify({"error": "payload_too_large"}), 413

    @routes.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @routes.errorhandler(ValueError)
    def invalid_request(_exc):
        return jsonify({"error": "onboarding_request_invalid"}), 400

    @routes.errorhandler(RuntimeError)
    def unavailable(_exc):
        return jsonify({"error": "onboarding_not_configured"}), 503

    @routes.post("/api/onboarding/events")
    def identity_event():
        # Every lifecycle field comes from the verified assertion, never the body.
        claims = _assertion("nija-onboarding-events", "NIJA_ONBOARDING_IDENTITY_SECRET",
                            required=("application_id", "email", "email_verified", "event_type"))
        key = outbox.ingest_identity_event(claims)
        return jsonify({"message_key": key, "member_activated": False}), 202

    @routes.post("/api/onboarding/resend/webhook")
    def resend_webhook():
        secret = os.getenv("RESEND_ONBOARDING_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise RuntimeError("webhook_not_configured")
        event = verify_resend_event(request.get_data(), request.headers, secret)
        outbox.record_provider_event(event["data"].get("email_id"), event.get("type"))
        return jsonify({"received": True})

    @routes.get("/api/onboarding/status")
    def member_status():
        claims = _assertion("nija-onboarding-status", "NIJA_ONBOARDING_IDENTITY_SECRET")
        try:
            status = outbox.member_status(claims["sub"])
        except KeyError:
            return jsonify({"error": "member_not_found"}), 404
        # Only an existing immutable NIJA owner binding is considered. Email is
        # a consistency check, NEVER a lookup or subscription attachment method.
        customer = billing_store.get_customer(claims["sub"])
        try:
            mismatch = bool(customer and normalize_email(customer["email"]) != status["canonical_email"])
        except ValueError:
            mismatch = True
        linked = bool(customer and not mismatch and customer["entitled"] and status["registered"])
        status.update(entitlement_linked=linked, identity_reconciliation_required=mismatch,
                      broker_connection_ready=False, member_activated=False,
                      activation_status="requires_independent_authenticated_readiness")
        status.pop("canonical_email")
        return jsonify(status)

    def operator():
        claims = _assertion("nija-onboarding-operator", "NIJA_ONBOARDING_OPERATOR_SECRET",
                            required=("scope",))
        if claims["scope"] != "onboarding:operate":
            raise ValueError("operator_required")

    @routes.get("/api/onboarding/operator/alerts")
    def alerts():
        operator()
        entries = outbox.alerts()
        return jsonify({"alerts": entries}), 503 if entries else 200

    @routes.post("/api/onboarding/operator/redrive")
    def redrive():
        operator()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("key"), str):
            raise ValueError("message_key_required")
        outbox.redrive(body["key"])
        return jsonify({"queued": True})

    def process_batch():
        mode = os.getenv("NIJA_ONBOARDING_SEND_MODE", "disabled")
        if mode not in ("controlled", "enabled"):
            raise RuntimeError("customer_sends_disabled")
        sender = os.getenv("NIJA_ONBOARDING_SENDER", "").strip()
        address = normalize_email(sender)
        if address.split("@")[1] != "nijaaitrading.com":
            raise RuntimeError("authenticated_sender_required")
        if (not os.getenv("RESEND_API_KEY") or not os.getenv("RESEND_ONBOARDING_WEBHOOK_SECRET")
                or os.getenv("NIJA_ONBOARDING_DOMAIN_VERIFIED") != "true"):
            raise RuntimeError("verified_provider_configuration_required")
        allowlist = {normalize_email(e) for e in os.getenv("NIJA_ONBOARDING_TEST_RECIPIENTS", "").split(",") if e}
        states = []
        errors = 0
        for key in outbox.due_keys(recipients=allowlist if mode == "controlled" else None):
            try:
                states.append(outbox.send(key, sender=sender))
            except sqlite3.Error:
                errors += 1
                app.logger.error("Onboarding worker storage error: key=%s", key)
        return {"processed": len(states), "errors": errors,
                "alerts": outbox.alerts(), "timestamp": int(time.time())}

    @routes.post("/api/onboarding/operator/work")
    def work():
        operator()
        return jsonify(process_batch())

    @app.cli.command("onboarding-worker")
    @click.option("--once", is_flag=True, help="Process a bounded batch, then exit.")
    def worker(once: bool) -> None:
        """Run under a process supervisor with the web service's durable volume."""
        while True:
            try:
                result = process_batch()
                app.logger.info("Onboarding worker processed=%s alerts=%s errors=%s",
                                result["processed"], len(result["alerts"]), result["errors"])
            except sqlite3.Error:
                app.logger.error("Onboarding worker storage unavailable")
                if once:
                    raise
            if once:
                return
            time.sleep(30)

    app.register_blueprint(routes)
