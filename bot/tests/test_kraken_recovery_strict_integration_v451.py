"""Review-only regression tests for v372 authenticated query evidence."""
from bot.kraken_authenticated_execution_evidence_v451 import validate_kraken_order_evidence


def test_authenticated_account_mismatch_is_rejected():
    order = {"txid": "ORDER-1", "status": "closed", "vol_exec": "1",
             "cost": "250", "descr": {"pair": "ETHUSD", "type": "buy"}}
    outcome = validate_kraken_order_evidence(
        "ORDER-1", "platform:kraken", order,
        authenticated_account_id="user:other:kraken",
        event_epoch=1000, now_epoch=1100,
    )
    assert outcome["verified"] is False


def test_freshness_is_exchange_event_based_not_query_time():
    order = {"txid": "ORDER-1", "status": "closed", "vol_exec": "1",
             "cost": "250", "descr": {"pair": "ETHUSD", "type": "buy"}}
    outcome = validate_kraken_order_evidence(
        "ORDER-1", "platform:kraken", order,
        authenticated_account_id="platform:kraken",
        event_epoch=1000, now_epoch=2801,
    )
    assert outcome["reason"] == "broker_event_stale_or_future"
