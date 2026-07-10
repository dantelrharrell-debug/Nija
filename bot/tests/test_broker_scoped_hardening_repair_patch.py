from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from bot import broker_scoped_hardening_repair_patch as patch


class FakeHardening:
    def __init__(self, broker_type="coinbase", **kwargs):
        self.broker_type = broker_type
        self.kwargs = kwargs

    def validate_order_hardening(
        self,
        symbol,
        side,
        position_size_usd,
        balance,
        current_positions,
        user_id=None,
        force_liquidate=False,
    ):
        return True, "ok", {
            "balance": balance,
            "positions": list(current_positions),
        }


def test_scopes_positions_and_uses_selected_broker_equity(monkeypatch):
    authority_module = ModuleType("bot.capital_authority")
    authority = SimpleNamespace(
        registered_broker_count=3,
        get_per_broker=lambda broker: {
            "coinbase": 71.45,
            "kraken": 333.40,
            "okx": 146.27,
        }.get(str(broker).lower(), 0.0),
    )
    authority_module.get_capital_authority = lambda: authority
    monkeypatch.setitem(sys.modules, "bot.capital_authority", authority_module)

    hardening_module = ModuleType("bot.execution_layer_hardening")
    hardening_module.ExecutionLayerHardening = FakeHardening
    hardening_module.get_execution_layer_hardening = (
        lambda broker_type="coinbase", **kwargs: FakeHardening(broker_type, **kwargs)
    )

    assert patch._patch(hardening_module) is True
    kraken = hardening_module.get_execution_layer_hardening("kraken")
    coinbase = hardening_module.get_execution_layer_hardening("coinbase")

    assert kraken is not coinbase
    passed, reason, details = kraken.validate_order_hardening(
        symbol="APT-USD",
        side="BUY",
        position_size_usd=27.56,
        balance=116.09,
        current_positions=[
            {"symbol": "ADA-USD", "broker": "kraken"},
            {"symbol": "ETH-USD", "broker": "kraken"},
            {"symbol": "SOL-USD", "broker": "coinbase"},
            {"symbol": "UNKNOWN-USD"},
        ],
    )

    assert passed is True
    assert reason == "ok"
    assert details["effective_tier_balance"] == 333.40
    assert details["raw_position_count"] == 4
    assert details["scoped_position_count"] == 2
    assert [position["symbol"] for position in details["positions"]] == [
        "ADA-USD",
        "ETH-USD",
    ]
