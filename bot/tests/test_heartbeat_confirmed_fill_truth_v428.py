from bot.trading_strategy import (
    _heartbeat_result_has_confirmed_submission,
    _heartbeat_result_is_confirmed_fill,
)


def test_state_unknown_without_order_id_is_not_heartbeat_success():
    result = {
        "status": "state_unknown",
        "error": "confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_60s",
        "order_id": "",
    }
    assert _heartbeat_result_has_confirmed_submission(result) is False
    assert _heartbeat_result_is_confirmed_fill(result) is False


def test_pending_requires_real_order_id_and_is_not_fill():
    assert _heartbeat_result_has_confirmed_submission({"status": "pending", "order_id": ""}) is False
    assert _heartbeat_result_has_confirmed_submission({"status": "pending", "order_id": "OID-1"}) is True
    assert _heartbeat_result_is_confirmed_fill({"status": "pending", "order_id": "OID-1"}) is False


def test_filled_requires_positive_fill_price_and_size():
    assert _heartbeat_result_is_confirmed_fill({
        "status": "filled", "order_id": "OID-1", "filled_price": 2500.0, "filled_size_usd": 28.75
    }) is True
    assert _heartbeat_result_is_confirmed_fill({
        "status": "filled", "order_id": "OID-1", "filled_price": 0.0, "filled_size_usd": 28.75
    }) is False
    assert _heartbeat_result_is_confirmed_fill({
        "status": "filled", "order_id": "OID-1", "filled_price": 2500.0, "filled_size_usd": 0.0
    }) is False


def test_success_word_without_fill_evidence_is_not_confirmed_fill():
    assert _heartbeat_result_is_confirmed_fill({"status": "success"}) is False
    assert _heartbeat_result_has_confirmed_submission({"status": "success", "order_id": ""}) is False
