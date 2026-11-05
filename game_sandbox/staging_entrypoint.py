"""Fail-closed Render entrypoint for a *separate* Trading IQ sandbox.

Do not import this module from NIJA's live billing or trading services.
No checkout routes exist until an operator explicitly configures a dedicated
sandbox origin and test-only Stripe credentials and enables the feature.
"""
from __future__ import annotations

import os


def create_staging_app():
    from flask import Flask, jsonify

    if os.environ.get("NIJA_IQ_SANDBOX_ENABLED") == "true":
        # from_environment fails closed if Stripe test credentials, manifest,
        # dedicated persistent disk, exact origin, or report integrity are missing.
        from .app import from_environment

        app = from_environment()

        @app.get("/healthz")
        def enabled_health():
            return jsonify(
                service="nija-iq72-staging",
                environment="stripe_test_only",
                live_payments=False,
                status="sandbox_configured",
            )

        return app

    app = Flask("nija_iq72_disabled_stage")

    @app.get("/healthz")
    def disabled_health():
        return jsonify(
            service="nija-iq72-staging",
            environment="disabled",
            live_payments=False,
            checkout_available=False,
            status="staging_holding",
        )

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def disabled_all(path):
        return jsonify(
            error="sandbox_not_enabled",
            checkout_available=False,
            live_payments=False,
        ), 503

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    return app


application = create_staging_app()
