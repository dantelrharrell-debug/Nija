from bot.runtime_coinbase_fill_truth_v345_patch import (
    _enrich_coinbase_ack_with_fill,
    _extract_order_id,
    _known_non_exchange_health,
)


def test_nested_coinbase_order_id_is_ack_proof():
    payload = {
        "status": "filled",
        "order": {
            "success": True,
            "success_response": {"order_id": "cb-order-123", "product_id": "BTC-USD"},
        },
        "filled_size": 0.001,
    }
    assert _extract_order_id(payload) == "cb-order-123"


def test_coinbase_ack_reconciles_fill_from_read_only_get_order():
    class Client:
        def get_order(self, *, order_id):
            assert order_id == "cb-order-123"
            return {
                "order": {
                    "order_id": order_id,
                    "status": "FILLED",
                    "average_filled_price": "77000.25",
                    "filled_size": "0.001",
                }
            }

    class CoinbaseBroker:
        broker_type = type("BrokerType", (), {"value": "coinbase"})()
        client = Client()

    payload = {
        "status": "filled",
        "order": {"success_response": {"order_id": "cb-order-123"}},
        "filled_size": 0.001,
    }
    enriched = _enrich_coinbase_ack_with_fill(CoinbaseBroker(), payload)
    assert enriched["order_id"] == "cb-order-123"
    assert enriched["status"] == "filled"
    assert enriched["filled_price"] == 77000.25
    assert enriched["filled_size"] == 0.001
    assert enriched["filled_size_usd"] == 77.00025
    assert enriched["coinbase_order_reconciled"] is True


def test_ack_without_fill_price_is_not_fabricated():
    class Client:
        def get_order(self, *, order_id):
            return {"order": {"order_id": order_id, "status": "OPEN", "filled_size": "0"}}

    class CoinbaseBroker:
        broker_type = type("BrokerType", (), {"value": "coinbase"})()
        client = Client()

    payload = {"status": "filled", "order": {"success_response": {"order_id": "pending-1"}}}
    enriched = _enrich_coinbase_ack_with_fill(CoinbaseBroker(), payload)
    assert enriched["order_id"] == "pending-1"
    assert enriched["status"] == "open"
    assert "filled_price" not in enriched
    assert "filled_size_usd" not in enriched


def test_dust_and_ack_pending_are_not_exchange_health_rejects():
    assert _known_non_exchange_health(
        "Exchange response lacks real order id; fill not proven: {'status': 'skipped_dust', 'error': 'INVALID_SIZE'}"
    )
    assert _known_non_exchange_health(
        "ACK timeout pending reconciliation order_id=abc status=filled reason=fill_specific_price_or_notional_missing"
    )


def test_historical_nested_success_is_non_exchange_health_but_not_fill_proof():
    reason = (
        "Exchange response lacks real order id; fill not proven: "
        "{'status': 'filled', 'order': {'success': True, 'success_response': {'order_id': 'abc'}}}"
    )
    assert _known_non_exchange_health(reason)


def test_unknown_exchange_rejection_remains_exchange_health_candidate():
    assert not _known_non_exchange_health("exchange rejected order: SERVICE_UNAVAILABLE")
    assert not _known_non_exchange_health("invalid api key")
