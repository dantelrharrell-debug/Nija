"""v432: Conservative, read-only research ranking across explicitly supported markets.

No broker SDK, environment mutation, order creation, or runtime patch installation.
This is NOT an execution gate or proof of profitability. Candidate assumptions and
holdout metrics are *claims supplied to research* until independently audited.
Only canonical confirmed-close P&L may establish actual winners/losers.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

MARKER = "20261008-research-net-edge-v432"
SUPPORTED_RESEARCH_VENUES = {
    "crypto_spot": frozenset({"kraken", "coinbase", "okx", "alpaca"}),
    "us_equity": frozenset({"alpaca"}),
    "us_etf": frozenset({"alpaca"}),
}
# Capability discovery and paid data permissions are separate from execution.
REQUIRES_NEW_FEEDS_AND_AUTHORIZATION = (
    "international_equity", "forex", "futures", "options", "commodities",
    "fixed_income", "crypto_derivatives",
)
COST_FIELDS = (
    "entry_fee_bps", "exit_fee_bps", "slippage_roundtrip_bps",
    "market_impact_bps", "carry_and_borrow_bps",
)
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._:/-]{0,47}$")
_STRATEGY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive_integer(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
        return number if number > 0 and float(value) == number else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def capability_inventory() -> dict[str, Any]:
    """Report integration scope without mistaking API listings for trade access."""
    return {
        "scope": "catalog_and_shadow_research_not_live_execution",
        "supported_research_venues": {
            asset: sorted(venues)
            for asset, venues in SUPPORTED_RESEARCH_VENUES.items()
        },
        "additional_classes_not_authorized": list(REQUIRES_NEW_FEEDS_AND_AUTHORIZATION),
        "worldwide_coverage_verified": False,
        "live_execution_authorized": False,
        "broker_short_permission_inferred": False,
    }


def evaluate_shadow_candidate(
    idea: Mapping[str, Any],
    *,
    requested_account_scope: str,
    registered_strategies: Mapping[str, str],
    now_epoch_s: float,
    min_net_buffer_bps: float = 10.0,
) -> dict[str, Any]:
    """Evaluate one possible LONG/SHORT signal; NEVER returns an order instruction.

    Inputs come from an external, separately validated signal research pipeline.
    Research labels are not a substitute for broker permissions, independent
    backtests, signed fills, or production execution authority.
    """
    reasons: list[str] = []
    venue = str(idea.get("venue") or "").strip().lower()
    asset = str(idea.get("asset_class") or "").strip().lower()
    symbol = str(idea.get("symbol") or "").strip().upper()
    direction = str(idea.get("direction") or "").strip().upper()
    scope = str(idea.get("account_scope") or "").strip()
    strategy_id = str(idea.get("strategy_id") or "").strip()
    version = str(idea.get("strategy_version") or "").strip()
    if not requested_account_scope or not scope or scope != requested_account_scope:
        reasons.append("account_scope_mismatch")
    # A valid user scope is still wrong if it belongs to a different broker.
    # Never let the same asset price be treated as account-local authority.
    if not scope.endswith(":" + venue):
        reasons.append("account_venue_mismatch")
    if venue not in SUPPORTED_RESEARCH_VENUES.get(asset, frozenset()):
        reasons.append("asset_venue_research_not_configured")
    if not _SYMBOL.fullmatch(symbol):
        reasons.append("invalid_symbol")
    if direction not in {"LONG", "SHORT"}:
        reasons.append("direction_must_be_long_or_short")
    if not _STRATEGY.fullmatch(strategy_id) or registered_strategies.get(strategy_id) != version or not version:
        reasons.append("unregistered_or_unversioned_strategy")

    timestamp = _finite(idea.get("quote_epoch_s"))
    now = _finite(now_epoch_s)
    if timestamp is None or now is None or not (-2.0 <= now - timestamp <= 45.0):
        reasons.append("quote_missing_future_or_stale")
    bid, ask = _finite(idea.get("bid")), _finite(idea.get("ask"))
    spread = None
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        reasons.append("unverified_bid_ask")
    else:
        spread = 10000.0 * (ask - bid) / ((bid + ask) / 2.0)

    if idea.get("instrument_tradable") is not True or idea.get("market_data_rights_verified") is not True:
        reasons.append("instrument_or_market_data_not_verified")
    if asset in {"us_equity", "us_etf"} and idea.get("market_session_open") is not True:
        reasons.append("market_session_closed_or_unverified")

    if direction == "SHORT":
        if asset not in {"us_equity", "us_etf"} or venue != "alpaca":
            reasons.append("short_not_supported_on_spot_or_unconfigured_venue")
        elif idea.get("account_shorting_enabled") is not True:
            reasons.append("account_short_permission_not_verified")
        elif str(idea.get("borrow_status") or "").lower() != "easy_to_borrow":
            # HTB requires genuine locate reservation/readback, which the
            # current NIJA live adapter has not proven. Never infer it.
            reasons.append("fresh_easy_to_borrow_not_verified")
        else:
            verified_at = _finite(idea.get("borrow_verified_epoch_s"))
            if verified_at is None or now is None or not (-2.0 <= now - verified_at <= 60.0):
                reasons.append("short_borrow_proof_stale")

    expected = _finite(idea.get("expected_gross_move_bps"))
    conservative = _finite(idea.get("conservative_gross_move_bps"))
    volatility = _finite(idea.get("forecast_volatility_bps"))
    if (
        expected is None or conservative is None or volatility is None
        or expected <= 0 or conservative <= 0 or conservative > expected
        or volatility <= 0
    ):
        reasons.append("gross_edge_or_risk_assumption_invalid")

    costs_obj = idea.get("costs")
    costs: dict[str, float] = {}
    if not isinstance(costs_obj, Mapping) or idea.get("cost_model_verified") is not True:
        reasons.append("cost_model_unverified")
    else:
        for key in COST_FIELDS:
            number = _finite(costs_obj.get(key))
            if number is None or number < 0 or number > 10_000:
                reasons.append("missing_or_invalid_cost_" + key)
            else:
                costs[key] = number
    if direction == "SHORT" and costs.get("carry_and_borrow_bps", -1) < 0:
        reasons.append("short_carry_cost_unverified")

    evidence = idea.get("research_evidence")
    if not isinstance(evidence, Mapping):
        reasons.append("chronological_holdout_missing")
    else:
        sample = _positive_integer(evidence.get("holdout_trades"))
        folds = _positive_integer(evidence.get("walk_forward_folds"))
        net_exp = _finite(evidence.get("holdout_net_expectancy_bps"))
        factor = _finite(evidence.get("holdout_profit_factor"))
        dataset_id = str(evidence.get("dataset_id") or "")
        if (
            sample < 60 or folds < 3 or not dataset_id
            or evidence.get("chronological_holdout_verified") is not True
            or evidence.get("full_costs_in_holdout") is not True
            or net_exp is None or net_exp <= 0
            or factor is None or factor <= 1.0
        ):
            reasons.append("out_of_sample_net_edge_not_proven")

    total_cost = sum(costs.values()) + (spread or 0.0) if len(costs) == len(COST_FIELDS) and spread is not None else None
    net_conservative = conservative - total_cost if conservative is not None and total_cost is not None else None
    buffer = _finite(min_net_buffer_bps)
    if buffer is None or buffer < 0:
        reasons.append("invalid_research_buffer")
    elif net_conservative is not None and net_conservative <= buffer:
        reasons.append("conservative_net_edge_insufficient")
    elif net_conservative is None:
        reasons.append("conservative_net_edge_unverifiable")

    research_eligible = not reasons
    score = (
        net_conservative / volatility
        if research_eligible and net_conservative is not None and volatility is not None
        else None
    )
    return {
        "asset_class": asset,
        "venue": venue,
        "account_scope": scope,
        "symbol": symbol,
        "direction": direction,
        "strategy_id": strategy_id,
        "strategy_version": version,
        "classification": "shadow_research_only" if research_eligible else "blocked_in_research",
        "blockers": sorted(set(reasons)),
        "quote_spread_bps": round(spread, 4) if spread is not None else None,
        "explicit_roundtrip_cost_bps": round(total_cost, 4) if total_cost is not None else None,
        "conservative_net_edge_bps": round(net_conservative, 4) if net_conservative is not None else None,
        "shadow_risk_adjusted_score": round(score, 6) if score is not None else None,
        "out_of_sample_evidence_independently_audited": False,
        "historical_performance_guarantee": False,
        "live_execution_authorized": False,
        "orders_submitted": False,
        "automatic_position_sizing_changes": False,
    }


def rank_shadow_opportunities(
    ideas: Sequence[Mapping[str, Any]],
    *,
    requested_account_scope: str,
    registered_strategies: Mapping[str, str],
    now_epoch_s: float,
    max_reported: int = 25,
) -> dict[str, Any]:
    """Rank *research-only* prospects; never produce order/size/stop commands."""
    if not requested_account_scope:
        raise ValueError("explicit account scope required")
    cap = max(1, min(100, int(max_reported)))
    decisions = [
        evaluate_shadow_candidate(
            idea, requested_account_scope=requested_account_scope,
            registered_strategies=registered_strategies, now_epoch_s=now_epoch_s,
        )
        for idea in ideas
    ]
    valid = [x for x in decisions if x["classification"] == "shadow_research_only"]
    valid.sort(
        key=lambda x: (
            -float(x["shadow_risk_adjusted_score"]),
            -float(x["conservative_net_edge_bps"]),
            x["venue"], x["symbol"], x["strategy_id"],
        )
    )
    return {
        "marker": MARKER,
        "mode": "research_only_no_orders",
        "account_scope": requested_account_scope,
        "candidates_supplied": len(ideas),
        "research_eligible": len(valid),
        "blocked": len(decisions) - len(valid),
        "ranked": valid[:cap],
        "blocker_diagnostics": [x for x in decisions if x["blockers"]][:cap],
        "capabilities": capability_inventory(),
        "live_execution_authorized": False,
        "orders_submitted": False,
        "automatic_position_sizing_changes": False,
        "profitability_proven": False,
    }
