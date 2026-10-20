"""Focused offline tests for account-scoped read-only reconciliation rules."""
from bot.pretrade_broker_evidence_checks import reconcile_order_fills, verify_protective_orders


def test_fill_reconciliation_rejects_missing_duplicate_and_wrong_account():
    fill = dict(account="platform:kraken", order_id="O-1", trade_id="T-1",
                symbol="ETHUSD", side="buy", quantity="0.1", cost="220", fee="0.5")
    assert reconcile_order_fills("platform:kraken", [fill], [fill])[0]
    assert not reconcile_order_fills("platform:kraken", [fill], [])[0]
    assert not reconcile_order_fills("platform:kraken", [fill, fill], [fill])[0]
    assert not reconcile_order_fills("user:other:kraken", [fill], [fill])[0]


def test_protection_requires_authenticated_reducing_open_order():
    position = dict(account="platform:kraken", symbol="ETHUSD", side="long", quantity="0.1")
    order = dict(account="platform:kraken", symbol="ETHUSD", side="sell",
                 status="open", order_id="O-exit", remaining_quantity="0.1",
                 protective_verified=True, reduce_only_verified=True)
    assert verify_protective_orders("platform:kraken", [position], [order])[0]
    assert not verify_protective_orders("platform:kraken", [position], [])[0]
    assert not verify_protective_orders("platform:kraken", [position],
                                       [{**order, "reduce_only_verified": False}])[0]
    assert not verify_protective_orders("platform:kraken", [position],
                                       [{**order, "remaining_quantity": "0.01"}])[0]
