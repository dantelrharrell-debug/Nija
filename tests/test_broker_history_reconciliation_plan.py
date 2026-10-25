from bot.broker_history_reconciliation_plan import plan_opening_reconciliation
import pytest


def fill(trade, order, account="platform:kraken"):
    return {"account": account, "broker_trade_id": trade, "broker_order_id": order}


def test_missing_history_never_authorizes_orders():
    result = plan_opening_reconciliation("platform:kraken", [fill("t1", "o1")], [])
    assert result["missing_opening_record_trade_ids"] == ["t1"]
    assert result["can_apply_migration"] is False
    assert result["authorizes_orders"] is False
    assert result["unknown_strategy_attribution_preserved"] is True


def test_exact_match_is_idempotent():
    rows = [fill("t1", "o1")]
    assert plan_opening_reconciliation("platform:kraken", rows, rows)["matched_trade_ids"] == ["t1"]


def test_conflicting_order_is_ambiguous():
    result = plan_opening_reconciliation("platform:kraken", [fill("t1", "o1")], [fill("t1", "other")])
    assert result["ambiguous_trade_ids"] == ["t1"]


def test_duplicate_broker_trade_is_ambiguous():
    result = plan_opening_reconciliation("platform:kraken", [fill("t1", "o1"), fill("t1", "o1")], [])
    assert result["ambiguous_trade_ids"] == ["t1"]


def test_account_scope_mismatch_fails_closed():
    with pytest.raises(ValueError):
        plan_opening_reconciliation("platform:kraken", [fill("t1", "o1", "platform:coinbase")], [])
