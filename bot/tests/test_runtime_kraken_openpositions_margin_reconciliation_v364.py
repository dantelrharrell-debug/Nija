from __future__ import annotations

import copy
import importlib

import pytest


v364 = importlib.import_module("bot.runtime_kraken_openpositions_margin_reconciliation_v364_patch")


def _valid_response():
    return {"error": [], "result": {"TX": {
        "pair": "XETHZUSD", "type": "buy", "vol": "0.5", "vol_closed": "0.1",
        "cost": "1200", "value": "1000", "margin": "600",
    }}}


@pytest.mark.parametrize("response", [
    {}, {"result": {}}, {"error": []}, {"error": [], "result": None},
    {"error": [], "result": []}, {"error": [], "result": False},
    {"error": None, "result": {}}, {"error": "", "result": {}},
    {"error": {}, "result": {}},
])
def test_malformed_envelope_never_reports_an_empty_account(response):
    assert v364._extract_long_margin_truth(response, "ETH-USD")["ok"] is False


@pytest.mark.parametrize("field", ["vol", "vol_closed"])
@pytest.mark.parametrize("invalid", [None, True, False, "NaN", "Infinity", "-0.1", "private-value", {}])
def test_invalid_quantity_cannot_become_zero(field, invalid):
    response = _valid_response()
    response["result"]["TX"][field] = invalid
    before = copy.deepcopy(response)
    truth = v364._extract_long_margin_truth(response, "ETH-USD")
    assert truth["ok"] is False
    assert "private-value" not in str(truth)
    assert response == before


@pytest.mark.parametrize("field", ["vol", "vol_closed", "pair", "type"])
def test_missing_position_fields_are_not_flat_position_evidence(field):
    response = _valid_response()
    del response["result"]["TX"][field]
    assert v364._extract_long_margin_truth(response, "ETH-USD")["ok"] is False


@pytest.mark.parametrize("row", [None, [], {}, {"pair": ""}])
def test_unclassifiable_row_is_not_silently_omitted(row):
    response = _valid_response()
    response["result"]["unknown"] = row
    assert v364._extract_long_margin_truth(response, "ETH-USD")["ok"] is False


def test_closed_volume_cannot_exceed_original_volume():
    response = _valid_response()
    response["result"]["TX"]["vol_closed"] = "0.6"
    assert v364._extract_long_margin_truth(response, "ETH-USD")["ok"] is False


def test_only_explicit_empty_result_is_empty_position_evidence():
    truth = v364._extract_long_margin_truth({"error": [], "result": {}}, "ETH-USD")
    assert truth == {"ok": True, "found": False, "symbol": "ETH-USD"}


def test_rejected_payload_does_not_echo_exchange_error_text():
    truth = v364._extract_long_margin_truth({"error": ["private-payload"], "result": {}}, "ETH-USD")
    assert truth["ok"] is False
    assert "private-payload" not in str(truth)


def test_invalid_snapshot_never_reaches_margin_ledger(monkeypatch):
    class Broker:
        def _kraken_api_call(self, method, params):
            assert method == "OpenPositions"
            return {"error": []}

    real_import = v364.importlib.import_module

    def guarded_import(name):
        assert name != "bot.margin_position_ledger", "invalid snapshot reached a writable ledger"
        return real_import(name)

    monkeypatch.setattr(v364.importlib, "import_module", guarded_import)
    assert v364._reconcile_open_position(Broker(), "platform:kraken", "ETH-USD")["ok"] is False


@pytest.mark.parametrize("field", ["value", "cost", "margin"])
@pytest.mark.parametrize("invalid", [None, True, "NaN", "Infinity", "-1", "private-payload"])
def test_malformed_valuation_does_not_fall_back_to_another_field(field, invalid):
    response = _valid_response()
    response["result"]["TX"][field] = invalid
    truth = v364._extract_long_margin_truth(response, "ETH-USD")
    assert truth["ok"] is False
    assert "private-payload" not in str(truth)


def test_aggregate_overflow_cannot_reach_position_authority():
    response = _valid_response()
    response["result"]["TX"]["value"] = "1e308"
    response["result"]["TX2"] = dict(response["result"]["TX"])
    assert v364._extract_long_margin_truth(response, "ETH-USD")["ok"] is False


def test_valid_zero_value_preserves_existing_cost_fallback():
    response = _valid_response()
    response["result"]["TX"]["value"] = "0"
    truth = v364._extract_long_margin_truth(response, "ETH-USD")
    assert truth["ok"] is True
    assert truth["notional_usd"] == 960.0
    assert truth["confirmed_fill_proof"] is False


def test_extracts_legacy_eth_long_without_creating_fill_proof():
    response = {
        "error": [],
        "result": {
            "TX-ETH": {
                "pair": "XETHZUSD",
                "type": "buy",
                "vol": "0.50000000",
                "vol_closed": "0.10000000",
                "cost": "1200.00",
                "value": "1000.00",
                "margin": "600.00",
            }
        },
    }
    truth = v364._extract_long_margin_truth(response, "ETH-USD")
    assert truth["ok"] is True
    assert truth["found"] is True
    assert truth["symbol"] == "ETH-USD"
    assert abs(truth["remaining_units"] - 0.4) < 1e-12
    assert abs(truth["notional_usd"] - 1000.0) < 1e-12
    assert truth["leverage"] == 2
    assert truth["broker_position_state_only"] is True
    assert truth["confirmed_fill_proof"] is False


def test_aggregates_multiple_same_direction_open_positions():
    response = {
        "error": [],
        "result": {
            "A": {"pair": "XETHZUSD", "type": "buy", "vol": "0.2", "vol_closed": "0", "value": "500", "cost": "500", "margin": "250"},
            "B": {"pair": "XETHZUSD", "type": "buy", "vol": "0.3", "vol_closed": "0.1", "value": "450", "cost": "600", "margin": "300"},
        },
    }
    truth = v364._extract_long_margin_truth(response, "ETH-USD")
    assert truth["ok"] is True
    assert truth["found"] is True
    assert abs(truth["remaining_units"] - 0.4) < 1e-12
    assert abs(truth["notional_usd"] - 950.0) < 1e-12
    assert set(truth["position_ids"]) == {"A", "B"}


def test_mixed_direction_same_pair_fails_closed():
    response = {
        "error": [],
        "result": {
            "LONG": {"pair": "XETHZUSD", "type": "buy", "vol": "0.2", "vol_closed": "0", "value": "500"},
            "SHORT": {"pair": "XETHZUSD", "type": "sell", "vol": "0.1", "vol_closed": "0", "value": "250"},
        },
    }
    truth = v364._extract_long_margin_truth(response, "ETH-USD")
    assert truth["ok"] is False
    assert truth["ambiguous"] is True
    assert truth["reason"] == "mixed_direction_openpositions"


def test_openpositions_error_is_not_position_authority():
    truth = v364._extract_long_margin_truth(
        {"error": ["EAPI:Invalid nonce"], "result": {}}, "ETH-USD"
    )
    assert truth["ok"] is False
    assert truth["reason"] == "openpositions_rejected"


def test_no_matching_open_position_does_not_promote_margin():
    truth = v364._extract_long_margin_truth(
        {"error": [], "result": {"BTC": {"pair": "XXBTZUSD", "type": "buy", "vol": "1", "vol_closed": "0", "value": "100"}}},
        "ETH-USD",
    )
    assert truth["ok"] is True
    assert truth["found"] is False


def test_known_margin_intent_requires_leverage_and_live_lifecycle():
    assert v364._known_margin_intent({"lifecycle_status": "pending_open", "leverage": 2}) is True
    assert v364._known_margin_intent({"lifecycle_status": "open", "leverage": 3}) is True
    assert v364._known_margin_intent({"lifecycle_status": "closed", "leverage": 2}) is False
    assert v364._known_margin_intent({"lifecycle_status": "pending_open", "leverage": 1}) is False


def test_proxy_broker_reconciles_live_margin_position(monkeypatch):
    response = {
        "error": [],
        "result": {
            "TX-ETH": {
                "pair": "XETHZUSD", "type": "buy", "vol": "0.5",
                "vol_closed": "0.1", "cost": "1200", "value": "1000", "margin": "600",
            }
        },
    }

    class Target:
        def _kraken_api_call(self, method, params):
            assert method == "OpenPositions"
            assert params == {"docalcs": "true"}
            return response

    class Proxy:
        def __init__(self):
            self._broker = Target()

    class Ledger:
        def reconcile_snapshot(self, **kwargs):
            assert kwargs["broker_units"] == 0.4
            return {"record": {"lifecycle_status": "open", "leverage": 2}}

    ledger_module = type("LedgerModule", (), {"get_margin_position_ledger": staticmethod(lambda: Ledger())})
    real_import = importlib.import_module

    def module_import(name):
        if name == "bot.margin_position_ledger":
            return ledger_module
        return real_import(name)

    monkeypatch.setattr(v364.importlib, "import_module", module_import)
    truth = v364._reconcile_open_position(Proxy(), "platform:kraken", "ETH-USD")

    assert truth["ok"] is True
    assert truth["found"] is True
    assert truth["remaining_units"] == 0.4


def test_extract_does_not_touch_execution_readiness_environment(monkeypatch):
    monkeypatch.setenv("NIJA_EXECUTION_READY", "0")
    monkeypatch.setenv("NIJA_TRADING_ENGINE_READY", "0")
    response = {
        "error": [],
        "result": {
            "TX": {"pair": "XETHZUSD", "type": "buy", "vol": "0.2", "vol_closed": "0", "value": "500", "cost": "500", "margin": "250"}
        },
    }
    truth = v364._extract_long_margin_truth(response, "ETH-USD")
    assert truth["found"] is True
    import os
    assert os.environ["NIJA_EXECUTION_READY"] == "0"
    assert os.environ["NIJA_TRADING_ENGINE_READY"] == "0"
