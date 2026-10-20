"""Execution-verification v2 *reference only*: isolated, read-only classifiers.

This module cannot place orders, write to ledgers, alter readiness, or grant
trading authority. Inputs are simulated/external observations whose actual
authenticated provenance must be established by a separately reviewed adapter.
Do NOT use these outputs as the production trading gate.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
from typing import Any, Mapping


PREFLIGHT_FACTS = (
    "live_trading_authorized", "account_identity_verified",
    "broker_permissions_verified", "authenticated_order_query_healthy",
    "account_snapshot_complete", "capital_publication_fresh",
    "positions_reconciled", "open_orders_reconciled",
    "cost_basis_reconciled", "protective_exits_verified",
    "risk_policy_ready", "writer_fence_ready", "nonce_ready",
    "kill_switch_clear", "strategy_ready", "account_isolation_verified",
)


def _positive_finite_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not result.is_finite() or result <= 0:
        return None
    return result


def classify_preflight(
    facts: Mapping[str, Any], *, sampled_at_epoch: float,
    now_epoch: float, max_snapshot_age_s: float,
) -> dict[str, Any]:
    """Describe a potential current account preflight, never authorizing.

    The externally supplied facts must come from independently verified broker
    and policy evidence, NOT from locally fabricated or cached "ready" bits.
    No age or proof of the last trade is requested or used.
    """
    missing = [key for key in PREFLIGHT_FACTS if facts.get(key) is not True]
    try:
        sampled, now, maximum = map(float, (sampled_at_epoch, now_epoch, max_snapshot_age_s))
        age = now - sampled
        fresh = bool(
            all(math.isfinite(v) for v in (sampled, now, maximum, age))
            and sampled > 0 and maximum > 0 and -5.0 <= age <= maximum
        )
    except (ValueError, TypeError, OverflowError):
        fresh = False
    if not fresh:
        missing.append("authenticated_account_snapshot_fresh")
    return {
        "preflight_candidate_observed": not missing,
        "preflight_missing": tuple(sorted(missing)),
        "diagnostic_only": True,
        "execution_authority_granted": False,
        "old_execution_marker_ignored_for_preflight": True,
    }


def classify_broker_observation(
    intent: Mapping[str, Any],
    observation: Mapping[str, Any],
    *, prior_fill_digests: Mapping[str, str],
) -> dict[str, Any]:
    """Stateless per-intent verifier reference; never posts ledger entries.

    A production implementation MUST authenticate source streams / REST reads
    and bind tenant/account/portfolio before invoking any verifier. The
    attested source fields here are fixtures for contract testing only.
    """
    result: dict[str, Any] = {
        "diagnostic_only": True, "execution_authority_granted": False,
        "ledger_mutated": False, "new_order_allowed": False,
        "status": "quarantine", "reason": "incomplete_or_mismatched_observation",
    }
    match_keys = ("tenant_id", "account_fingerprint", "venue",
                  "portfolio_id", "client_order_id", "symbol", "side")
    for key in match_keys:
        a, b = intent.get(key), observation.get(key)
        if not isinstance(a, str) or not a or a != b:
            result["reason"] = "identity_mismatch:" + key
            return result
    # A broker-order ID must agree with the persisted intent for every
    # event, including acknowledgements and terminal status transitions.
    expected_order_id = intent.get("broker_order_id")
    observed_order_id = observation.get("broker_order_id")
    if not isinstance(observed_order_id, str) or not observed_order_id:
        result["reason"] = "broker_order_id_missing"
        return result
    if expected_order_id and observed_order_id != expected_order_id:
        result["reason"] = "broker_order_identity_mismatch"
        return result
    if observation.get("authenticated_by_adapter") is not True:
        result["reason"] = "authenticated_broker_source_missing"
        return result
    if observation.get("source") not in ("private_ws", "authenticated_rest"):
        result["reason"] = "broker_source_not_allowlisted"
        return result
    kind = observation.get("event_kind")
    if kind == "acknowledged":
        if not observation.get("broker_order_id"):
            result["reason"] = "broker_order_id_missing"
            return result
        return {**result, "status": "ack_only", "reason": "no_execution_proven"}
    if kind in ("canceled", "rejected", "expired"):
        # This report does not prove zero fills, even if terminal.
        return {**result, "status": "terminal_unreconciled",
                "reason": "verify_cumulative_fills_before_close"}
    if kind not in ("fill", "partial_fill"):
        result["reason"] = "unsupported_event_kind"
        return result
    if not isinstance(observation.get("broker_order_id"), str) or not observation["broker_order_id"]:
        result["reason"] = "broker_order_id_missing"
        return result
    exec_id = observation.get("execution_id")
    if not isinstance(exec_id, str) or not exec_id:
        result["reason"] = "execution_id_missing"
        return result
    quantity = _positive_finite_decimal(observation.get("fill_qty"))
    price = _positive_finite_decimal(observation.get("fill_price"))
    requested = _positive_finite_decimal(intent.get("requested_qty"))
    cumulative = _positive_finite_decimal(observation.get("cumulative_qty"))
    if any(v is None for v in (quantity, price, requested, cumulative)):
        result["reason"] = "invalid_or_nonfinite_fill"
        return result
    if cumulative > requested or quantity > cumulative:
        result["reason"] = "overfill_or_inconsistent_cumulative_quantity"
        return result
    digest = observation.get("canonical_execution_digest")
    if not isinstance(digest, str) or len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        result["reason"] = "execution_digest_missing_or_invalid"
        return result
    prior = prior_fill_digests.get(exec_id)
    if prior is not None:
        return {**result, "status": "duplicate" if prior == digest else "quarantine",
                "reason": "identical_fill_replay" if prior == digest else "conflicting_execution_id"}
    return {
        **result, "status": "fill_candidate_for_reconciliation",
        "reason": "broker_execution_id_present_ledger_and_positions_unverified",
        "execution_id": exec_id,
        "fill_qty": str(quantity), "fill_price": str(price),
        "cumulative_qty": str(cumulative),
    }


__all__ = ["PREFLIGHT_FACTS", "classify_preflight", "classify_broker_observation"]
