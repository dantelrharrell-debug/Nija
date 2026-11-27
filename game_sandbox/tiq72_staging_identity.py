"""Unmounted NIJA authentication issuer for synthetic Trading IQ TEST users."""
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from flask import Flask, jsonify, request

from auth.user_database import UserDatabase

AUDIENCE = "nija-tiq72-customer-test"
SCOPE = "APPROVED_TIQ72_SYNTHETIC_ONLY"
SUBJECT = re.compile(r"tiq-stage-[a-z0-9-]{1,64}\Z")
EMAIL = re.compile(r"tiq-stage-[a-z0-9-]{1,64}@example\.invalid\Z")
MAX_BODY = 2048


def _config_secret(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value) is not None


def create_issuer(*, scope, accounts, jwt_key, bridge_key):
    """Expose only auth routes; deployment must enforce private ingress and rate limits."""
    if (
        scope != SCOPE or not _config_secret(jwt_key)
        or not _config_secret(bridge_key) or hmac.compare_digest(jwt_key, bridge_key)
    ):
        raise ValueError("synthetic_staging_identity_configuration_required")

    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=MAX_BODY)

    @app.after_request
    def private_headers(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.before_request
    def require_private_bridge():
        supplied = request.headers.get("X-NIJA-Staging-Bridge", "")
        if len(supplied) != len(bridge_key) or not hmac.compare_digest(supplied.encode(), bridge_key.encode()):
            return jsonify(error="unavailable"), 404

    def active_user(subject):
        if not isinstance(subject, str) or not SUBJECT.fullmatch(subject):
            return None
        row = accounts.get_user(subject)
        if not row or row.get("enabled") is not True or not EMAIL.fullmatch(row.get("email", "")):
            return None
        return row

    @app.post("/api/auth/login")
    def login():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {"email", "password"}:
            return jsonify(error="invalid_request"), 400
        email, password = data["email"], data["password"]
        if not isinstance(email, str) or not EMAIL.fullmatch(email) or not isinstance(password, str) or not 1 <= len(password) <= 256:
            return jsonify(error="invalid_credentials"), 401
        row = accounts.get_user_by_email(email)
        subject = row.get("user_id") if row else None
        if not active_user(subject) or not accounts.verify_password(subject, password):
            return jsonify(error="invalid_credentials"), 401
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {"iss": AUDIENCE, "aud": AUDIENCE, "sub": subject, "iat": now, "exp": now + timedelta(minutes=15)},
            jwt_key, algorithm="HS256"
        )
        return jsonify(access_token=token, token_type="Bearer")

    @app.get("/api/user/profile")
    def profile():
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) > 4096:
            return jsonify(error="invalid_session"), 401
        try:
            claims = jwt.decode(
                authorization[7:], jwt_key, algorithms=["HS256"], issuer=AUDIENCE, audience=AUDIENCE,
                options={"require": ["iss", "aud", "sub", "iat", "exp"]},
            )
        except jwt.InvalidTokenError:
            return jsonify(error="invalid_session"), 401
        if not active_user(claims["sub"]):
            return jsonify(error="invalid_session"), 401
        return jsonify(user_id=claims["sub"], enabled=True)

    return app


def from_environment():
    """Guard the isolated persistent file; never fall back to relative users.db."""
    if (
        os.environ.get("NIJA_TIQ72_ISSUER_SCOPE") != SCOPE
        or os.environ.get("STRIPE_LIVE_MODE", "").lower() == "true"
        or os.environ.get("TIQ72_LIVE_PAYMENTS_ENABLED", "").lower() == "true"
    ):
        raise ValueError("synthetic_staging_identity_configuration_required")
    signing = os.environ.get("NIJA_TIQ72_ISSUER_JWT_KEY")
    bridge = os.environ.get("NIJA_TIQ72_ISSUER_BRIDGE_KEY")
    if not _config_secret(signing) or not _config_secret(bridge) or hmac.compare_digest(signing, bridge):
        raise ValueError("synthetic_staging_keys_required")
    mount = Path("/var/data/tiq72-auth")
    path = mount / "staging-only-users.sqlite3"
    expected = str(path)
    if (
        os.environ.get("NIJA_AUTH_USER_DB_PATH") != expected
        or os.environ.get("NIJA_USER_DB_PATH") != expected
        or not os.path.ismount(mount) or mount.resolve() != mount
        or path.is_symlink() or (path.exists() and not path.is_file())
    ):
        raise ValueError("verified_staging_auth_mount_required")
    return create_issuer(scope=SCOPE, accounts=UserDatabase(expected), jwt_key=signing, bridge_key=bridge)
