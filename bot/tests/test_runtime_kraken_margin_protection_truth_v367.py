from __future__ import annotations

import sys
import types

import pytest

from bot import runtime_kraken_margin_protection_truth_v367_patch as v367


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    v367._reset_state_for_tests()
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    yield
    v367._reset_state_for_tests()


def test_openorders_stop_requires_sell_and_remaining_quantity(monkeypatch):
    payload = {
        "error": [],
        "result": {
            "open": {
                "STOP1": {
                    "status": "open",
                    "descr": {"pair": "XETHZUSD", "type": "sell", "ordertype": "stop-loss"},
                    "vol": "0.13742703",
                    "vol_exec": "0",
                },
                "TP1": {
                    "status": "open",
                    "descr": {"pair": "XETHZUSD", "type": "sell", "ordertype": "take-profit"},
                    "vol": "0.13742703",
                    "vol_exec": "0",
                },
                "BUY1": {
                    "status": "open",
                    "descr": {"pair": "XETHZUSD", "type": "buy", "ordertype": "stop-loss"},
                    "vol": "99",
                    "vol_exec": "0",
                },
            }
        },
    }
    ok, rows, reason = v367._normalise_open_orders(payload)
    assert ok is True
    assert reason == "ok"
    assert rows["ETH-USD"]["stop_qty"] == pytest.approx(0.13742703)
    assert rows["ETH-USD"]["take_profit_qty"] == pytest.approx(0.13742703)
    assert rows["ETH-USD"]["stop_order_ids"] == ("STOP1",)
    assert rows["ETH-USD"]["take_profit_order_ids"] == ("TP1",)


def test_existing_risk_policy_uses_stricter_dollar_loss_cap():
    row = {
        "quantity": 0.13742703,
        "entry_price": 2498.6764976293243,
        "cost_basis_usd": 343.38569,
    }
    expected = 2.0 / 343.38569
    assert v367._effective_stop_loss_pct(row) == pytest.approx(expected)


def test_v365_margin_rows_receive_software_stop(monkeypatch):
    import bot.runtime_kraken_margin_protective_scan_v365_patch as v365

    original = v365._openposition_rows

    def base(_broker):
        return [
            {
                "symbol": "ETH-USD",
                "quantity": 0.13742703,
                "entry_price": 2498.6764976293243,
                "cost_basis_usd": 343.38569,
                "kraken_margin_openpositions": True,
            }
        ], "ok"

    monkeypatch.setattr(v365, "_openposition_rows", base)
    assert v367._patch_v365_margin_rows() is True
    rows, reason = v365._openposition_rows(object())
    assert reason == "ok"
    assert rows[0]["software_stop_loss_derived"] is True
    pct = 2.0 / 343.38569
    assert rows[0]["stop_loss"] == pytest.approx(2498.6764976293243 * (1.0 - pct))
    monkeypatch.setattr(v365, "_openposition_rows", original)


def test_coverage_does_not_call_configuration_verified_without_native_or_live_software(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [
            {
                "account": "platform:kraken",
                "broker": "kraken",
                "symbol": "ETH-USD",
                "quantity": 0.13742703,
                "entry_price": 2498.6764976293243,
                "cost_basis": 343.38569,
                "margin_position": True,
                "protective_exit_verified": True,
                "exit_protections_attached": (
                    "stop_loss", "take_profit", "trailing_take_profit", "trailing_stop", "auto_exit_reconciler"
                ),
            }
        ], []

    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    monkeypatch.setattr(v367, "_native_protection", lambda account, broker: (True, {}, "ok"))
    monkeypatch.setattr(v367, "_software_protection_status", lambda: (False, "monitor_down"))
    assert v367._patch_v366_coverage() is True

    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())
    assert rows[0]["protective_exit_verified"] is False
    assert rows[0]["exit_protections_attached"] == ()
    assert rows[0]["protective_exit_mode"] == "unverified"
    assert "kraken_margin_protective_exit_unverified:ETH-USD" in reasons
    monkeypatch.setattr(v366, "margin_coverage_rows", original)


def test_native_stop_covering_position_is_verified(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [
            {
                "account": "platform:kraken",
                "broker": "kraken",
                "symbol": "ETH-USD",
                "quantity": 0.13742703,
                "entry_price": 2498.6764976293243,
                "cost_basis": 343.38569,
                "margin_position": True,
            }
        ], []

    native = {
        "ETH-USD": {
            "stop_qty": 0.13742703,
            "take_profit_qty": 0.0,
            "stop_order_ids": ("STOP1",),
            "take_profit_order_ids": (),
        }
    }
    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    monkeypatch.setattr(v367, "_native_protection", lambda account, broker: (True, native, "ok"))
    monkeypatch.setattr(v367, "_software_protection_status", lambda: (False, "monitor_down"))
    assert v367._patch_v366_coverage() is True

    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())
    assert reasons == []
    assert rows[0]["protective_exit_verified"] is True
    assert rows[0]["native_stop_loss_verified"] is True
    assert rows[0]["protective_exit_mode"] == "native_exchange_stop"
    assert rows[0]["exit_protections_attached"] == ("native_stop_loss",)
    monkeypatch.setattr(v366, "margin_coverage_rows", original)


def test_queryorders_exact_fill_can_recover_execution_proof(monkeypatch):
    broker = types.SimpleNamespace(connected=True)

    calls = []

    def private_call(method, params):
        calls.append((method, dict(params)))
        if method == "OpenPositions":
            return {
                "error": [],
                "result": {
                    "POS1": {
                        "pair": "XETHZUSD",
                        "type": "buy",
                        "vol": "0.13742703",
                        "vol_closed": "0",
                        "opentm": str(__import__("time").time() - 60),
                        "ordertxid": "OPENORDER1",
                    }
                },
            }
        if method == "QueryOrders":
            assert params["txid"] == "OPENORDER1"
            return {
                "error": [],
                "result": {
                    "OPENORDER1": {
                        "status": "closed",
                        "vol_exec": "0.13742703",
                        "cost": "343.38569",
                        "price": "2498.6764976293243",
                        "descr": {"pair": "XETHZUSD", "type": "buy"},
                    }
                },
            }
        raise AssertionError(method)

    broker._kraken_api_call = private_call
    monkeypatch.setattr(v367, "_account_brokers", lambda: [("platform:kraken", broker)])
    monkeypatch.setattr(v367, "_execution_marker_ready", lambda: (False, "marker_missing"))

    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366
    monkeypatch.setattr(v366, "_private_call", lambda _broker: private_call)

    accepted = []

    import bot.runtime_confirmed_fill_profitability_v328_patch as v328
    original = v328._normalize_dict_fill

    def normalize(result, *, symbol, side):
        accepted.append((dict(result), symbol, side))
        return result["filled_price"], result["filled_quantity"] * result["filled_price"]

    monkeypatch.setattr(v328, "_normalize_dict_fill", normalize)

    fake_v346 = types.SimpleNamespace(
        _wake_activation_after_proof=lambda: None,
        _wake_position_sync=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "bot.runtime_execution_position_readiness_v346_patch", fake_v346)

    assert v367.recover_execution_proof_once() == 1
    assert accepted
    result, symbol, side = accepted[0]
    assert result["order_id"] == "OPENORDER1"
    assert result["authenticated_kraken_queryorders"] is True
    assert symbol == "ETH-USD"
    assert side == "buy"
    assert any(method == "QueryOrders" for method, _params in calls)
    monkeypatch.setattr(v328, "_normalize_dict_fill", original)


def test_pending_queryorder_never_becomes_execution_proof(monkeypatch):
    broker = types.SimpleNamespace(connected=True)

    def private_call(method, params):
        if method == "OpenPositions":
            return {
                "error": [],
                "result": {
                    "POS1": {
                        "pair": "XETHZUSD",
                        "type": "buy",
                        "vol": "0.1",
                        "vol_closed": "0",
                        "opentm": str(__import__("time").time() - 60),
                        "ordertxid": "OPENORDER1",
                    }
                },
            }
        if method == "QueryOrders":
            return {
                "error": [],
                "result": {
                    "OPENORDER1": {
                        "status": "open",
                        "vol_exec": "0.1",
                        "cost": "250",
                        "price": "2500",
                        "descr": {"pair": "XETHZUSD", "type": "buy"},
                    }
                },
            }
        raise AssertionError(method)

    broker._kraken_api_call = private_call
    monkeypatch.setattr(v367, "_account_brokers", lambda: [("platform:kraken", broker)])
    monkeypatch.setattr(v367, "_execution_marker_ready", lambda: (False, "marker_missing"))

    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366
    monkeypatch.setattr(v366, "_private_call", lambda _broker: private_call)

    import bot.runtime_confirmed_fill_profitability_v328_patch as v328
    called = []
    monkeypatch.setattr(v328, "_normalize_dict_fill", lambda *args, **kwargs: called.append(True))

    assert v367.recover_execution_proof_once() == 0
    assert called == []
