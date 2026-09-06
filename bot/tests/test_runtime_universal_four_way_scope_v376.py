from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest

from bot import auto_exit_sl_tp_runtime_patch as auto_exit
from bot import runtime_universal_four_way_scope_v376_patch as v376
from bot import runtime_universal_sl_tp_policy_v375_patch as v375


@pytest.fixture(autouse=True)
def _four_way_env(monkeypatch):
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP1_PCT", "0.005")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP2_PCT", "0.010")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP3_PCT", "0.020")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_STOP_PCT", "0.0035")
    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_TP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_TP_CALLBACK_PCT", "0.0035")
    monkeypatch.setenv("NIJA_RUNTIME_UNIVERSAL_SL_TP_POLICY_V375_READY", "1")
    auto_exit._HIGH_WATER.clear()


class _Tracker:
    def get_all_positions(self):
        return []

    def get_position(self, _symbol):
        return None


class _FutureBroker:
    broker_type = "future_broker"
    account_id = "user:future"
    connected = True

    def __init__(self):
        self.position_tracker = _Tracker()

    def get_quote(self, _symbol):
        return {"price": 100.0}

    def execute_order(self, **_kwargs):
        return {"status": "filled", "order_id": "future-exit"}


class _NoCloseBroker(_FutureBroker):
    execute_order = None


class _PlatformBroker(_FutureBroker):
    broker_type = "kraken"
    account_id = "platform"


def _request(account_id, preferred_broker=None, **metadata):
    return SimpleNamespace(
        intent_type="entry",
        position_effect="open",
        metadata=metadata,
        account_id=account_id,
        preferred_broker=preferred_broker,
        asset_class="futures",
        symbol="ES",
        side="buy",
        size_usd=100.0,
        notional_usd=100.0,
    )


def _patch_scope_dependencies(monkeypatch, expected, registered):
    monkeypatch.setattr(v376, "_expected_accounts", lambda: dict(expected))
    monkeypatch.setattr(v376, "_canonical_brokers", lambda: [broker for broker in expected.values() if broker is not None])
    monkeypatch.setattr(v376, "_reconcile_supervisor", lambda _brokers=None: (True, set(registered)))
    monkeypatch.setattr(v376, "_asset_scope_self_test", lambda: (True, {"crypto": True, "future_market": True}))

    import bot.universal_broker_exit_supervisor_patch as supervisor

    monkeypatch.setitem(supervisor._STATE, "started", True)


def test_asset_scope_covers_every_canonical_class_and_future_market_label():
    ready, details = v376._asset_scope_self_test()

    assert ready is True
    assert {"crypto", "equity", "futures", "options"}.issubset(details)
    assert details["future_market"] is True


def test_policy_is_trade_type_and_market_metadata_agnostic():
    for asset_class, trade_type, side in (
        ("crypto", "spot", "long"),
        ("crypto", "margin", "short"),
        ("equity", "cash_equity", "long"),
        ("futures", "perpetual_future", "short"),
        ("options", "listed_option", "long"),
        ("future_market", "future_trade_type", "short"),
    ):
        row = v375._policy_row(
            {
                "account_id": "user:any",
                "position_id": f"{asset_class}-{trade_type}-{side}",
                "symbol": "TEST-MARKET",
                "side": side,
                "entry_price": 100.0,
                "quantity": 1.0,
                "asset_class": asset_class,
                "trade_type": trade_type,
                "leverage": 3 if trade_type in {"margin", "perpetual_future"} else 1,
                "order_type": "limit" if asset_class == "equity" else "market",
            }
        )
        assert row["asset_class"] == asset_class
        assert row["trade_type"] == trade_type
        assert row["software_stop_loss_available"] is True
        assert row["software_take_profit_available"] is True
        assert row["software_trailing_stop_available"] is True
        assert row["software_trailing_take_profit_available"] is True
        assert row["universal_four_way_policy_complete"] is True


def test_future_broker_contract_is_structural_not_name_based():
    capability = v376._broker_capability(_FutureBroker())

    assert capability["broker"] == "future-broker"
    assert capability["position_read"] is True
    assert capability["price_read"] is True
    assert capability["close_write"] is True


def test_selected_user_broker_without_close_path_fails_scope(monkeypatch):
    broker = _NoCloseBroker()
    expected = {"user:future:future-broker": broker}
    _patch_scope_dependencies(monkeypatch, expected, {id(broker)})

    ready, details = v376._scope_truth(_request("user:future", "future_broker"))

    assert ready is False
    assert details["selected_ready"] is False
    assert details["capabilities"][0]["close_write"] is False


def test_selected_future_broker_with_all_interfaces_passes_scope(monkeypatch):
    broker = _FutureBroker()
    expected = {"user:future:future-broker": broker}
    _patch_scope_dependencies(monkeypatch, expected, {id(broker)})

    ready, details = v376._scope_truth(_request("user:future", "future_broker"))

    assert ready is True
    assert details["selected_ready"] is True
    assert details["capabilities"][0]["registered"] is True
    assert details["capabilities"][0]["four_way_scope_ready"] is True


def test_broken_user_does_not_block_safe_platform_request(monkeypatch):
    platform = _PlatformBroker()
    broken_user = _NoCloseBroker()
    expected = {
        "platform:kraken": platform,
        "user:broken:future-broker": broken_user,
    }
    _patch_scope_dependencies(monkeypatch, expected, {id(platform), id(broken_user)})

    ready, details = v376._scope_truth(_request("platform", "kraken"))

    assert ready is True
    assert details["selection_mode"].startswith("platform_default")
    assert details["selected_accounts"] == ("platform:kraken",)


def test_broadcast_request_fails_if_any_selected_account_is_unprotected(monkeypatch):
    platform = _PlatformBroker()
    broken_user = _NoCloseBroker()
    expected = {
        "platform:kraken": platform,
        "user:broken:future-broker": broken_user,
    }
    _patch_scope_dependencies(monkeypatch, expected, {id(platform), id(broken_user)})

    ready, details = v376._scope_truth(_request("broadcast", None, broadcast_all_accounts=True))

    assert ready is False
    assert details["selection_mode"] == "broadcast"
    assert len(details["selected_accounts"]) == 2


def test_unknown_future_account_fails_closed(monkeypatch):
    platform = _PlatformBroker()
    expected = {"platform:kraken": platform}
    _patch_scope_dependencies(monkeypatch, expected, {id(platform)})

    ready, details = v376._scope_truth(_request("user:not-yet-registered", "future_broker"))

    assert ready is False
    assert details["selected_accounts"] == ()


def test_v376_preserves_legacy_profit_lock_ordering_before_supplemental_trailing():
    assert v375._patch_auto_exit_trigger() is True
    assert v376._patch_trigger_compatibility() is True

    pos = {
        "account_id": "platform",
        "position_id": "legacy-profit-lock",
        "symbol": "SOL-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
        "stop_loss": 98.0,
    }
    auto_exit._HIGH_WATER.clear()

    assert auto_exit._trigger(pos, 101.0)[0] is False
    hit, reason, _target = auto_exit._trigger(pos, 100.60)

    assert hit is True
    assert reason == "profit_lock_trailing_exit"


def test_pipeline_denial_is_fail_closed_but_exit_detection_is_preserved():
    @dataclass
    class PipelineResult:
        success: bool
        symbol: str
        side: str
        size_usd: float
        error: str

    module = ModuleType("fake_execution_pipeline")
    module.PipelineResult = PipelineResult
    entry = _request("user:future", "future_broker")
    exit_request = SimpleNamespace(
        intent_type="exit",
        position_effect="close",
        metadata={"closing_position": True},
    )

    denied = v376._pipeline_denial(module, entry, {"selected_ready": False})

    assert denied.success is False
    assert "selected account lacks four-way protective exit coverage" in denied.error
    assert v376._is_exit_request(exit_request) is True
