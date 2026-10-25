from bot.broker_history_reconciliation_plan import plan_opening_reconciliation as _plan_opening_reconciliation


def plan_opening_reconciliation(account, fills, ledger):
    return _plan_opening_reconciliation(account, fills, ledger,
        authenticated_readback=True, complete_pagination=True,
        account_identity_verified=True)
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
\n\ndef test_uncertified_readback_is_rejected():\n    with pytest.raises(ValueError, match="independent_broker_readback_certification_required"):\n        _plan_opening_reconciliation("platform:kraken", [fill("t1", "o1")], [])\n