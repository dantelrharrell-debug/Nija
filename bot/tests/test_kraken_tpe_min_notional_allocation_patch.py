from __future__ import annotations

import os
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from bot.kraken_tpe_min_notional_allocation_patch import patch_trade_permission_engine


def _module(decision):
    module = ModuleType("bot.trade_permission_engine")

    class TradePermissionEngine:
        def evaluate(self, *args, **kwargs):
            return decision

    module.TradePermissionEngine = TradePermissionEngine
    return module


def _decision(**updates):
    values = dict(
        symbol="ADA-USDT",
        side="long",
        broker="kraken",
        final_decision="EXECUTE",
        risk_allowed=True,
        capital_balance=234.30,
        capital_allocated=11.71485976101703,
    )
    values.update(updates)
    return SimpleNamespace(**values)


def test_approved_kraken_allocation_is_lifted_to_executable_floor():
    decision = _decision()
    module = _module(decision)
    assert patch_trade_permission_engine(module)
    with patch.dict(os.environ, {
        "NIJA_KRAKEN_TARGET_ORDER_USD": "23.10",
        "NIJA_MAX_POSITION_SIZE_PCT": "0.50",
    }, clear=False):
        result = module.TradePermissionEngine().evaluate(
            symbol="ADA-USDT", side="long", broker="kraken", balance=234.30
        )
    assert result.capital_allocated == 23.10
    assert result.final_decision == "EXECUTE"


def test_blocked_decision_is_never_converted_to_execute():
    decision = _decision(final_decision="BLOCKED", risk_allowed=False, capital_allocated=0.0)
    module = _module(decision)
    assert patch_trade_permission_engine(module)
    result = module.TradePermissionEngine().evaluate(
        symbol="ADA-USDT", side="long", broker="kraken", balance=234.30
    )
    assert result.final_decision == "BLOCKED"
    assert result.capital_allocated == 0.0


def test_lift_fails_closed_when_target_exceeds_account_risk_cap():
    decision = _decision(capital_balance=104.94, capital_allocated=5.25)
    module = _module(decision)
    assert patch_trade_permission_engine(module)
    with patch.dict(os.environ, {
        "NIJA_KRAKEN_TARGET_ORDER_USD": "23.10",
        "NIJA_MAX_POSITION_SIZE_PCT": "0.20",
        "MAX_POSITION_PCT": "0.20",
    }, clear=False):
        result = module.TradePermissionEngine().evaluate(
            symbol="ADA-USDT", side="long", broker="kraken", balance=104.94
        )
    assert result.capital_allocated == 5.25


def test_non_kraken_and_exit_sides_are_unchanged():
    for broker, side in (("coinbase", "long"), ("kraken", "sell")):
        decision = _decision(broker=broker, side=side)
        module = _module(decision)
        assert patch_trade_permission_engine(module)
        result = module.TradePermissionEngine().evaluate(
            symbol="ADA-USDT", side=side, broker=broker, balance=234.30
        )
        assert result.capital_allocated == 11.71485976101703
