"""Isolated, disabled-by-default NIJA member broker credential intake API.

Deploy as an independent service, never in the trading runtime. This service
does not submit broker orders or claim to verify exchange connectivity.
"""
from __future__ import annotations

import os
from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest

from bot.member_broker_vault import BrokerVault, VaultError
from bot.member_broker_onboarding import MemberBrokerOnboarding
from member_broker_entitlement import trusted_founding_entitlement


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
                vault, secret_intake_enabled=os.environ.get(
                    "NIJA_VAULT_INTAKE_ENABLED", ""
                ) == "true",
            )
        except (KeyError, VaultError, ValueError):
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

    @app.route("/api/member/brokers", methods=["GET", "OPTIONS"])
    @app.route("/api/member/brokers/connect", methods=["POST", "OPTIONS"])
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
        except (VaultError, BadRequest, TypeError, ValueError, KeyError):
            # Do not echo provider errors, token or any submitted credentials.
            return jsonify({"error": "broker_connection_unavailable_or_denied"}), 403

    return app


app = create_app()
