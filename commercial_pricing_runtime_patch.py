"""Runtime integration for NIJA's canonical commercial pricing policy.

This keeps commercial offers independent from legacy access/permission tiers while
ensuring public registration and pricing responses cannot advertise stale tier
prices.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import jsonify, request

from commercial_offer_store import get_commercial_offer_store
from pricing_policy import FOUNDING_BETA_LIMIT, beta_offer_for_claimed_count, public_pricing


def _response_status(response: Any) -> int:
    if isinstance(response, tuple) and len(response) >= 2:
        return int(response[1])
    return int(getattr(response, "status_code", 200))


def _response_object(response: Any) -> Any:
    return response[0] if isinstance(response, tuple) else response


def _wrap_registration(original: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        # Public clients may not self-select internal access/permission tiers.
        # Mutating Flask's cached JSON mapping before the legacy handler reads it
        # lets the existing registration path remain backward compatible while
        # preventing privilege selection through a customer-facing field.
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            payload["subscription_tier"] = "basic"

        result = original(*args, **kwargs)
        if _response_status(result) != 201:
            return result

        response = _response_object(result)
        body = response.get_json(silent=True) if hasattr(response, "get_json") else None
        if not isinstance(body, dict) or not body.get("user_id"):
            return result

        assignment = get_commercial_offer_store().assign_beta_offer(str(body["user_id"]))
        body["commercial_offer"] = assignment.to_dict()
        body["pricing_policy"] = {
            "lessons_one_time_usd": 99.0,
            "full_release_planned_monthly_usd": 99.0,
        }
        response.set_data(response.json_module.dumps(body))
        response.content_type = "application/json"
        return result

    return wrapped


def _canonical_available_offers() -> Any:
    store = get_commercial_offer_store()
    claimed = store.founding_beta_claimed_count()
    current = beta_offer_for_claimed_count(claimed)
    return jsonify({
        "success": True,
        "commercial_offers": public_pricing(),
        "beta": {
            "founding_limit": FOUNDING_BETA_LIMIT,
            "founding_claimed": claimed,
            "founding_remaining": max(0, FOUNDING_BETA_LIMIT - claimed),
            "current_offer": current.to_dict(),
        },
        "access_tiers_are_internal": True,
        "disclaimer": "Trading and investing involve risk, including possible loss of capital. No profit or performance results are guaranteed.",
    })


def _wrap_subscription_info(original: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if _response_status(result) >= 400:
            return result
        response = _response_object(result)
        body = response.get_json(silent=True) if hasattr(response, "get_json") else None
        user_id = getattr(request, "user_id", None)
        if not isinstance(body, dict) or not isinstance(user_id, str):
            return result
        assignment = get_commercial_offer_store().get_assignment(user_id)
        if assignment:
            body["commercial_offer"] = assignment.to_dict()
            response.set_data(response.json_module.dumps(body))
            response.content_type = "application/json"
        return result

    return wrapped


def install_commercial_pricing_runtime_patch(app: Any) -> None:
    """Install idempotent integration after all NIJA blueprints are registered."""
    if app.extensions.get("nija_commercial_pricing_patch"):
        return

    register_endpoint = "register"
    original_register = app.view_functions.get(register_endpoint)
    if original_register is not None:
        app.view_functions[register_endpoint] = _wrap_registration(original_register)

    tiers_endpoint = "unified_mobile_api.get_available_tiers"
    if tiers_endpoint in app.view_functions:
        app.view_functions[tiers_endpoint] = _canonical_available_offers

    info_endpoint = "unified_mobile_api.get_subscription_info"
    original_info = app.view_functions.get(info_endpoint)
    if original_info is not None:
        app.view_functions[info_endpoint] = _wrap_subscription_info(original_info)

    app.extensions["nija_commercial_pricing_patch"] = True
