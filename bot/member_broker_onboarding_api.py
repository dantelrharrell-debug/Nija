"""Opt-in authenticated NIJA member broker-credential API.

Only mount this blueprint after verifying PocketBase owner rules, trusted billing
entitlements, HTTPS routing and encryption key deployment. Never mounts itself.
This API stores encrypted credentials only; it cannot submit trades.
"""
from __future__ import annotations

import os
from typing import Callable

from flask import Blueprint, jsonify, request

from bot.member_broker_vault import BrokerVault, VaultError, BROKERS, ENVIRONMENTS


def make_member_broker_blueprint(entitlement_check: Callable[[str], bool]) -> Blueprint:
    """Require operator-confirmed production gates and an injected trusted verifier."""
    if os.environ.get("NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED") != "true":
        raise RuntimeError("Production owner-bound vault rules not verified")
    if not callable(entitlement_check):
        raise RuntimeError("Trusted member entitlement verifier required")
    vault = BrokerVault.from_environment(entitlement_check)
    bp = Blueprint("member_broker_credentials", __name__, url_prefix="/api/member/brokerages")

    def bearer() -> str:
        header = request.headers.get("Authorization", "")
        kind, separator, token = header.partition(" ")
        if kind.lower() != "bearer" or not separator or not token or any(c.isspace() for c in token):
            raise VaultError("Authentication required")
        return token

    @bp.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    @bp.route("", methods=["GET"])
    def connections():
        try:
            return jsonify({"connections": vault.list_metadata(bearer()), "trading_enabled": False})
        except VaultError:
            return jsonify({"error": "Brokerage setup unavailable or unauthorized"}), 403

    @bp.route("", methods=["POST"])
    def add_connection():
        if not request.is_json:
            return jsonify({"error": "JSON required"}), 415
        if request.content_length is None or request.content_length > 4096:
            return jsonify({"error": "Invalid credential payload size"}), 413
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {"broker", "environment", "credentials"}:
            return jsonify({"error": "Invalid broker setup fields"}), 400
        broker, environment, credentials = data["broker"], data["environment"], data["credentials"]
        if broker not in BROKERS or environment not in ENVIRONMENTS:
            return jsonify({"error": "Unsupported brokerage"}), 400
        if not isinstance(credentials, dict) or not credentials or any(
            not isinstance(k, str) or not isinstance(v, str) or not k or not v
            for k, v in credentials.items()
        ):
            return jsonify({"error": "Invalid credential fields"}), 400
        try:
            record_id = vault.create(bearer(), broker, environment, credentials)
            return jsonify({
                "id": record_id, "broker": broker, "environment": environment,
                "status": "stored_pending_verification", "trading_enabled": False
            }), 201
        except VaultError:
            return jsonify({"error": "Brokerage setup unavailable or unauthorized"}), 403

    return bp
