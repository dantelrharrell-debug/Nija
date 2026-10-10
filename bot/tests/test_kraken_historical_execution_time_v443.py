"""Fail-closed regression checks for historical Kraken QueryOrders evidence."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from bot import runtime_kraken_margin_execution_proof_liveness_v372_patch as v372


def _opening():
    return {"order_id": "EXCHANGE-ORDER", "position_id": "MARGIN-POS",
            "symbol": "BTCUSD", "side": "buy"}


def _payload(**changes):
    row = {"status": "closed", "vol_exec": "0.01", "cost": "800",
           "price": "80000", "closetm": str(time.time() - 60),
           "descr": {"pair": "XBTUSD", "type": "buy"}}
    row.update(changes)
    return {"error": [], "result": {"EXCHANGE-ORDER": row}}


def _query(payload):
    def call(endpoint, params):
        assert endpoint == "QueryOrders"
        assert params["txid"] == "EXCHANGE-ORDER"
        return payload
    return call


@pytest.mark.parametrize("changes,reason", [
    ({"closetm": ""}, "queryorders_broker_fill_time_unproven"),
    ({"closetm": str(time.time() + 3600)}, "queryorders_broker_fill_time_unproven"),
    ({"descr": {"pair": "ETHUSD", "type": "buy"}}, "queryorders_opening_identity_mismatch"),
    ({"descr": {"pair": "XBTUSD", "type": "sell"}}, "queryorders_opening_identity_mismatch"),
    ({"descr": {"type": "buy"}}, "queryorders_symbol_side_unproven"),
])
def test_reject_unproven_historical_evidence(changes, reason):
    with patch.object(v372, "_v366") as module:
        module.return_value.canonical_symbol = lambda v: {
            "XBTUSD": "BTCUSD", "XXBTZUSD": "BTCUSD"
        }.get(str(v), str(v))
        proof, detail = v372._exact_queryorders_fill(_query(_payload(**changes)), _opening())
    assert proof is None
    assert detail == reason


def test_valid_old_fill_retains_event_time_and_recovery_label():
    old = time.time() - 7200
    with patch.object(v372, "_v366") as module:
        module.return_value.canonical_symbol = lambda v: {
            "XBTUSD": "BTCUSD"
        }.get(str(v), str(v))
        proof, detail = v372._exact_queryorders_fill(
            _query(_payload(closetm=str(old))), _opening())
    assert detail == "ok"
    assert proof["broker_fill_at_epoch"] == pytest.approx(old)
    assert proof["recovered_fill_proof"] is True
    assert proof["broker"] == "kraken"
    assert proof["authenticated_kraken_queryorders"] is True
    assert proof["opening_position_id"] == "MARGIN-POS"


def test_nonfinal_order_is_not_execution_proof():
    proof, detail = v372._exact_queryorders_fill(
        _query(_payload(status="open")), _opening())
    assert proof is None
    assert detail == "queryorders_nonfinal:open"
