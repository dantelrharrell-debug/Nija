"""HTTP routes for NIJA's canonical commercial pricing policy."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from commercial_offer_store import get_commercial_offer_store
from pricing_policy import (
    FOUNDING_BETA_LIMIT,
    public_pricing,
    beta_offer_for_claimed_count,
)

pricing_api = Blueprint("pricing_api", __name__)


@pricing_api.get("/api/commercial/pricing")
def get_public_pricing():
    """Return canonical public pricing plus the currently advertised beta offer."""
    store = get_commercial_offer_store()
    claimed = store.founding_beta_claimed_count()
    current = beta_offer_for_claimed_count(claimed)
    return jsonify({
        "pricing": public_pricing(),
        "beta": {
            "founding_limit": FOUNDING_BETA_LIMIT,
            "founding_claimed": claimed,
            "founding_remaining": max(0, FOUNDING_BETA_LIMIT - claimed),
            "current_offer": current.to_dict(),
        },
        "disclaimer": "Trading and investing involve risk, including possible loss of capital. No profit or performance results are guaranteed.",
    })


@pricing_api.get("/api/commercial/offer/<user_id>")
def get_user_commercial_offer(user_id: str):
    """Return a user's locked commercial offer assignment.

    This route intentionally requires the same user's authenticated identity to be
    injected by the surrounding gateway before production exposure. If no such
    identity is present, it fails closed.
    """
    authenticated_user_id = getattr(request, "user_id", None)
    if not authenticated_user_id:
        return jsonify({"error": "Authentication required"}), 401
    if authenticated_user_id != user_id:
        return jsonify({"error": "Forbidden"}), 403

    assignment = get_commercial_offer_store().get_assignment(user_id)
    if not assignment:
        return jsonify({"error": "Commercial offer not assigned"}), 404
    return jsonify(assignment.to_dict())
