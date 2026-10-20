"""Offline acceptance tests: never contact an exchange or authorize dispatch."""
from bot.kraken_authenticated_execution_evidence_v451 import validate_kraken_order_evidence


def sample():
    return dict(txid="A-123", status="closed", vol_exec="0.25",
                cost="500.00", descr={"pair": "ETHUSD", "type": "buy"})


def check(order=None, **changes):
    args = dict(order_id="A-123", account_id="platform:kraken",
                order=sample() if order is None else order,
                authenticated_account_id="platform:kraken",
                event_epoch=1000.0, now_epoch=1100.0)
    args.update(changes)
    return validate_kraken_order_evidence(**args)


def test_exact_recent_completed_fill_is_diagnostic_only():
    result = check()
    assert result["verified"] is True
    assert result["authorization_granted"] is False
    assert result["order_id"] == "A-123"
    assert result["vol_exec"] == 0.25
    assert result["cost"] == 500.0
    assert result["broker_event_at_epoch"] == 1000.0


def test_reject_different_authenticated_account():
    assert check(authenticated_account_id="user:other")["verified"] is False


def test_reject_different_order_id():
    assert check(order_id="OTHER")["reason"] == "order_identity_mismatch"


def test_reject_open_or_cancelled_order():
    for status in ("open", "canceled", "expired"):
        order = sample()
        order["status"] = status
        assert check(order)["verified"] is False


def test_reject_zero_or_nan_execution():
    for field, value in (("vol_exec", "0"), ("cost", "0"),
                         ("vol_exec", "nan"), ("cost", "inf")):
        order = sample()
        order[field] = value
        assert check(order)["verified"] is False


def test_reject_old_or_future_broker_event():
    assert check(now_epoch=2801)["reason"] == "broker_event_stale_or_future"
    assert check(now_epoch=990)["reason"] == "broker_event_stale_or_future"


def test_missing_timestamp_does_not_use_observation_time():
    assert check(event_epoch=0)["verified"] is False


def test_reject_missing_pair_and_side():
    order = sample()
    order["descr"] = {"pair": "ETHUSD"}
    assert check(order)["verified"] is False


def test_cannot_extend_freshness_limit():
    assert check(max_age_seconds=7200)["verified"] is False
