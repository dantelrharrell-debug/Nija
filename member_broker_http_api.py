"""Isolated, disabled-by-default NIJA member broker credential intake API.

Deploy as an independent service, never in the trading runtime. Kraken verification
is read-only authentication, never order submission or trading authorization.
"""
from __future__ import annotations

import logging
import os
from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest

from member_broker_vault import BrokerVault, VaultError
from member_broker_onboarding import MemberBrokerOnboarding
from member_broker_entitlement import trusted_founding_entitlement
from member_broker_kraken_readonly import KrakenVerificationError


REVIEW_FLAGS = (
    "NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED",
    "NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED",
    "NIJA_MEMBER_BROKER_BILLING_ENTITLEMENT_VERIFIED",
    "NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED",
)
BILLING_SETTINGS = (
    "NIJA_VAULT_BILLING_READONLY_URL", "NIJA_VAULT_STRIPE_READONLY_KEY",
    "NIJA_VAULT_FOUNDING_PRICE_ID", "NIJA_VAULT_FOUNDING_PRODUCT_ID",
)


def _reviewed_configuration() -> bool:
    return (
        all(os.environ.get(name) == "true" for name in REVIEW_FLAGS)
        and all(os.environ.get(name, "").strip() for name in BILLING_SETTINGS)
    )


LOGGER = logging.getLogger("nija.member_broker_http_api")


def _readiness_blocker(onboarding: MemberBrokerOnboarding | None) -> str | None:
    """Return a fixed non-secret reason; never echo environment names or values."""
    if onboarding is None:
        return "vault_unavailable"
    if any(os.environ.get(name) != "true" for name in REVIEW_FLAGS):
        return "security_review_incomplete"
    if any(not os.environ.get(name, "").strip() for name in BILLING_SETTINGS):
        return "billing_configuration_incomplete"
    if not (onboarding.secret_intake_enabled or onboarding.verification_enabled):
        return "capabilities_disabled"
    return None


def create_app(*, onboarding: MemberBrokerOnboarding | None = None) -> Flask:
    """Construct the standalone, fail-closed HTTPS service."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 12_288
    allowed = frozenset(
        origin.strip() for origin in
        os.environ.get("NIJA_VAULT_ALLOWED_ORIGINS", "https://nijaaitrading.com").split(",")
        if origin.strip().startswith("https://")
    )
    if onboarding is None:
        try:
            vault = BrokerVault.from_environment(trusted_founding_entitlement)
            onboarding = MemberBrokerOnboarding(
                vault, secret_intake_enabled=(
                    os.environ.get("NIJA_VAULT_INTAKE_ENABLED", "") == "true"
                    and _reviewed_configuration()
                ),
                verification_enabled=(
                    os.environ.get("NIJA_VAULT_VERIFICATION_ENABLED", "") == "true"
                    and _reviewed_configuration()
                ),
            )
        except (KeyError, VaultError, ValueError) as exc:
            # Never log exception text: vault exceptions may contain secrets.
            LOGGER.warning(
                "MEMBER_BROKER_VAULT_INIT_FAILED reason=vault_unavailable error_type=%s",
                type(exc).__name__,
            )
            onboarding = None

    @app.after_request
    def secure_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        origin = request.headers.get("Origin", "")
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.route("/healthz", methods=["GET"])
    def health():
        return jsonify({"service": "nija-member-broker", "status": "ok"})

    @app.route("/readyz", methods=["GET"])
    def readiness():
        # Health is process liveness; readiness requires configured vault and
        # trusted entitlement backend. Never disclose missing secret names.
        blocker = _readiness_blocker(onboarding)
        if blocker is not None:
            # Log only a fixed category, not variable names, tokens, or values.
            LOGGER.warning("MEMBER_BROKER_READINESS ready=false reason=%s", blocker)
            return jsonify({"status": "not_ready"}), 503
        return jsonify({"status": "ready", "credential_intake_enabled": onboarding.secret_intake_enabled,
                        "verification_enabled": onboarding.verification_enabled}), 200

    @app.route("/api/member/brokers", methods=["GET", "OPTIONS"])
    @app.route("/api/member/brokers/connect", methods=["POST", "OPTIONS"])
    @app.route("/api/member/brokers/verify", methods=["POST", "OPTIONS"])
    def members():
        if request.method == "OPTIONS":
            return ("", 204) if request.headers.get("Origin") in allowed else ("", 403)
        if request.headers.get("Origin") not in allowed:
            return jsonify({"error": "origin_not_allowed"}), 403
        if onboarding is None:
            return jsonify({"error": "credential_service_unavailable"}), 503
        auth = request.headers.get("Authorization", "").split()
        if len(auth) != 2 or auth[0].lower() != "bearer" or not auth[1]:
            return jsonify({"error": "authentication_required"}), 401
        try:
            if request.method == "GET":
                statuses = onboarding.connections(auth[1])
                return jsonify({"connections": [
                    {"broker": s.broker, "environment": s.environment,
                     "credentials_stored": s.credentials_stored,
                     "broker_verified": False, "trading_authorized": False}
                    for s in statuses
                ]})
            if request.mimetype != "application/json":
                return jsonify({"error": "json_required"}), 415
            payload = request.get_json(silent=False)
            if request.path == "/api/member/brokers/verify":
                if not isinstance(payload, dict) or set(payload) != {"broker", "environment"}:
                    return jsonify({"error": "invalid_request"}), 400
                result = onboarding.verify(auth[1], payload["broker"], payload["environment"])
                return jsonify({
                    "broker": result.broker, "environment": result.environment,
                    "credentials_stored": result.credentials_stored,
                    "broker_verified": result.broker_verified,
                    "membership_access": True, "trading_authorized": False,
                })
            if not isinstance(payload, dict) or set(payload) != {
                "broker", "environment", "credentials"
            }:
                return jsonify({"error": "invalid_request"}), 400
            result = onboarding.connect(
                auth[1], payload["broker"], payload["environment"], payload["credentials"]
            )
            return jsonify({"broker": result.broker, "environment": result.environment,
                            "credentials_stored": result.credentials_stored,
                            "broker_verified": False, "trading_authorized": False}), 201
        except KrakenVerificationError:
            return jsonify({"error": "broker_verification_unavailable", "broker_verified": False,
                            "trading_authorized": False}), 502
        except (VaultError, BadRequest, TypeError, ValueError, KeyError):
            # Do not echo provider errors, token or any submitted credentials.
            return jsonify({"error": "broker_connection_unavailable_or_denied"}), 403

    return app


app = create_app()
