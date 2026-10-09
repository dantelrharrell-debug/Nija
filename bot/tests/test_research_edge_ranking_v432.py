"""Research-only v432 ranking tests; no broker/network/account mutations."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from bot.research_edge_ranking_v432 import (
    capability_inventory,
    evaluate_shadow_candidate,
    rank_shadow_opportunities,
)


def candidate(**changes):
    baseline = {
        "venue": "kraken",
        "asset_class": "crypto_spot",
        "symbol": "BTC-USD",
        "direction": "LONG",
        "account_scope": "platform:kraken",
        "strategy_id": "trend_breakout",
        "strategy_version": "v7",
        "quote_epoch_s": 1000,
        "bid": 100,
        "ask": 100.04,
        "instrument_tradable": True,
        "market_data_rights_verified": True,
        "expected_gross_move_bps": 150.0,
        "conservative_gross_move_bps": 120.0,
        "forecast_volatility_bps": 70.0,
        "cost_model_verified": True,
        "costs": {
            "entry_fee_bps": 22,
            "exit_fee_bps": 22,
            "slippage_roundtrip_bps": 10,
            "market_impact_bps": 5,
            "carry_and_borrow_bps": 0,
        },
        "research_evidence": {
            "holdout_trades": 150,
            "walk_forward_folds": 6,
            "dataset_id": "market-replay-v3",
            "chronological_holdout_verified": True,
            "full_costs_in_holdout": True,
            "holdout_net_expectancy_bps": 20,
            "holdout_profit_factor": 1.23,
        },
    }
    baseline.update(changes)
    return baseline


def evaluate(item, **kwargs):
    return evaluate_shadow_candidate(
        item,
        requested_account_scope="platform:kraken",
        registered_strategies={"trend_breakout": "v7"},
        now_epoch_s=1020.0,
        **kwargs,
    )


def test_eligible_long_is_shadow_only_and_never_grants_execution():
    r = evaluate(candidate())
    assert r["classification"] == "shadow_research_only"
    assert r["blockers"] == []
    assert r["shadow_risk_adjusted_score"] is not None
    assert r["conservative_net_edge_bps"] > 10
    assert r["live_execution_authorized"] is False
    assert r["orders_submitted"] is False
    assert r["automatic_position_sizing_changes"] is False


@pytest.mark.parametrize("field,value,blocker", [
    ("venue", "unknown", "asset_venue_research_not_configured"),
    ("asset_class", "international_equity", "asset_venue_research_not_configured"),
    ("account_scope", "user:other:kraken", "account_scope_mismatch"),
    ("direction", "SELL", "direction_must_be_long_or_short"),
    ("strategy_version", "v100", "unregistered_or_unversioned_strategy"),
    ("quote_epoch_s", 870, "quote_missing_future_or_stale"),
    ("quote_epoch_s", 1050, "quote_missing_future_or_stale"),
    ("bid", 105.0, "unverified_bid_ask"),
    ("ask", 0.0, "unverified_bid_ask"),
    ("instrument_tradable", False, "instrument_or_market_data_not_verified"),
    ("market_data_rights_verified", False, "instrument_or_market_data_not_verified"),
    ("expected_gross_move_bps", -2.0, "gross_edge_or_risk_assumption_invalid"),
    ("conservative_gross_move_bps", 200.0, "gross_edge_or_risk_assumption_invalid"),
    ("forecast_volatility_bps", 0, "gross_edge_or_risk_assumption_invalid"),
    ("cost_model_verified", False, "cost_model_unverified"),
])
def test_rejects_invalid_or_unproven_market_fields(field, value, blocker):
    data = candidate(**{field: value})
    assert blocker in evaluate(data)["blockers"]


@pytest.mark.parametrize("key,value", [
    ("entry_fee_bps", None),
    ("exit_fee_bps", -1),
    ("slippage_roundtrip_bps", float("nan")),
    ("market_impact_bps", float("inf")),
    ("carry_and_borrow_bps", -5.0),
])
def test_incomplete_or_invalid_roundtrip_costs_block(key, value):
    data = candidate()
    data["costs"][key] = value
    assert ("missing_or_invalid_cost_" + key) in evaluate(data)["blockers"]


def test_spread_plus_roundtrip_costs_exceed_gross_edge():
    data = candidate(
        bid=99.5, ask=100.5,
        conservative_gross_move_bps=95,
        expected_gross_move_bps=110,
    )
    decision = evaluate(data)
    assert decision["explicit_roundtrip_cost_bps"] > 100
    assert decision["classification"] == "blocked_in_research"
    assert "conservative_net_edge_insufficient" in decision["blockers"]


@pytest.mark.parametrize("problem", [
    {"holdout_trades": 30},
    {"walk_forward_folds": 1},
    {"dataset_id": ""},
    {"chronological_holdout_verified": False},
    {"full_costs_in_holdout": False},
    {"holdout_net_expectancy_bps": -0.5},
    {"holdout_profit_factor": 0.9},
])
def test_out_of_sample_quality_guard_does_not_accept_mere_backtest_claim(problem):
    data = candidate()
    data["research_evidence"].update(problem)
    assert "out_of_sample_net_edge_not_proven" in evaluate(data)["blockers"]


def test_research_rejects_cross_venue_prices_even_with_matching_requested_owner():
    data = candidate(venue="coinbase", account_scope="platform:kraken")
    assert "account_venue_mismatch" in evaluate(data)["blockers"]


def test_crypto_spot_cannot_short_by_borrowing_stock_permissions():
    data = candidate(direction="SHORT", account_shorting_enabled=True, borrow_status="easy_to_borrow")
    assert "short_not_supported_on_spot_or_unconfigured_venue" in evaluate(data)["blockers"]


@pytest.mark.parametrize("borrow,expected", [
    ("easy_to_borrow", True),
    ("hard_to_borrow", False),
    ("unavailable", False),
    ("unknown", False),
])
def test_us_equity_short_requires_all_current_permissions(borrow, expected):
    data = candidate(
        asset_class="us_equity",
        venue="alpaca", symbol="AAPL",
        account_scope="platform:alpaca",
        direction="SHORT",
        market_session_open=True, account_shorting_enabled=True,
        shortable=True, borrow_status=borrow,
        borrow_verified_epoch_s=1010.0,
    )
    r = evaluate_shadow_candidate(
        data, requested_account_scope="platform:alpaca",
        registered_strategies={"trend_breakout": "v7"},
        now_epoch_s=1020.0,
    )
    assert (r["classification"] == "shadow_research_only") is expected



@pytest.mark.parametrize("shortable", [None, False, "true", 1, 0])
def test_equity_short_requires_authenticated_individual_security_shortable(shortable):
    data = candidate(
        venue="alpaca", asset_class="us_equity", symbol="AAPL",
        account_scope="platform:alpaca", direction="SHORT",
        market_session_open=True, account_shorting_enabled=True,
        borrow_status="easy_to_borrow", borrow_verified_epoch_s=1010.0,
    )
    if shortable is not None:
        data["shortable"] = shortable
    result = evaluate_shadow_candidate(
        data, requested_account_scope="platform:alpaca",
        registered_strategies={"trend_breakout": "v7"}, now_epoch_s=1020.0,
    )
    assert result["classification"] == "blocked_in_research"
    assert "individual_security_shortable_not_verified" in result["blockers"]
    assert result["live_execution_authorized"] is False
    assert result["orders_submitted"] is False

def test_us_equity_short_stale_borrow_or_market_closed_blocks():
    data = candidate(
        venue="alpaca", asset_class="us_equity",
        symbol="NVDA", account_scope="platform:alpaca",
        direction="SHORT", account_shorting_enabled=True,
        shortable=True, borrow_status="easy_to_borrow",
        borrow_verified_epoch_s=800.0,
        market_session_open=False,
    )
    r = evaluate_shadow_candidate(
        data, requested_account_scope="platform:alpaca",
        registered_strategies={"trend_breakout": "v7"}, now_epoch_s=1020.0,
    )
    assert "short_borrow_proof_stale" in r["blockers"]
    assert "market_session_closed_or_unverified" in r["blockers"]


def test_global_shadow_ranking_keeps_accounts_and_consent_separate():
    weaker = candidate(symbol="ETH-USD", conservative_gross_move_bps=90)
    stronger = candidate(symbol="BTC-USD", conservative_gross_move_bps=160,
                         expected_gross_move_bps=170)
    excluded = candidate(symbol="DOGE-USD", account_scope="user:customer:kraken")
    result = rank_shadow_opportunities(
        [weaker, stronger, excluded],
        requested_account_scope="platform:kraken",
        registered_strategies={"trend_breakout": "v7"}, now_epoch_s=1020.0,
    )
    assert result["candidates_supplied"] == 3
    assert result["research_eligible"] == 2
    assert result["blocked"] == 1
    assert [x["symbol"] for x in result["ranked"]] == ["BTC-USD", "ETH-USD"]
    assert result["profitability_proven"] is False
    assert result["live_execution_authorized"] is False


def test_ranking_requires_explicit_account_scope():
    with pytest.raises(ValueError, match="account scope"):
        rank_shadow_opportunities(
            [candidate()], requested_account_scope="",
            registered_strategies={"trend_breakout": "v7"},
            now_epoch_s=1020.0,
        )


def test_global_inventory_does_not_infer_unlicensed_markets_or_permissions():
    inv = capability_inventory()
    assert inv["worldwide_coverage_verified"] is False
    assert inv["live_execution_authorized"] is False
    assert "international_equity" in inv["additional_classes_not_authorized"]
    assert "futures" in inv["additional_classes_not_authorized"]
    assert "options" in inv["additional_classes_not_authorized"]
    assert "crypto_spot" in inv["supported_research_venues"]


def test_research_module_never_imports_broker_stack_or_order_sender():
    path = Path(__file__).resolve().parents[1] / "research_edge_ranking_v432.py"
    source = path.read_text(encoding="utf-8")
    assert "import bot." not in source and "from bot." not in source
    for prohibited in ("place_market_order", "submit_order(", "execute_order(",
                       "TRADING_ENGINE_READY.set", "FORCE_TRADE=true",
                       "NIJA_FORCE_ACTIVATION=true"):
        assert prohibited not in source
