"""Offline acceptance tests: never contact an exchange or authorize dispatch."""
from bot.kraken_authenticated_execution_evidence_v451 import validate_kraken_order_evidence


def sample():
    return dict(txid="A-123", status="closed", vol_exec="0.25",
                cost="500.00", closetm=1000.0,
                descr={"pair": "ETHUSD", "type": "buy"})


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


def test_recent_observation_cannot_retimestamp_an_old_broker_close():
    order = sample()
    order["closetm"] = 100.0
    result = check(order, event_epoch=1050.0, now_epoch=1100.0)
    assert result == {"verified": False, "reason": "broker_event_timestamp_mismatch"}


def test_stale_close_cannot_be_refreshed_to_current_clock():
    order = sample()
    result = check(order, event_epoch=2790.0, now_epoch=2800.0)
    assert result["reason"] == "broker_event_timestamp_mismatch"


def test_missing_or_invalid_broker_close_time_denied():
    for value in (None, 0, -1, float("nan"), float("inf"), True, "bad"):
        order = sample()
        order["closetm"] = value
        assert check(order)["verified"] is False
    order = sample()
    del order["closetm"]
    assert check(order)["verified"] is False


def test_broker_close_time_strict_freshness_boundary():
    assert check(now_epoch=2800.0)["verified"] is True
    assert check(now_epoch=2800.000001)["verified"] is False
    assert check(now_epoch=995.0)["verified"] is True
    assert check(now_epoch=994.9)["reason"] == "broker_event_stale_or_future"


def test_event_assertion_only_matches_exact_broker_timestamp():
    assert check(event_epoch=1000.0000005)["verified"] is True
    assert check(event_epoch=1000.002)["reason"] == "broker_event_timestamp_mismatch"
    assert check(event_epoch=True)["verified"] is False
