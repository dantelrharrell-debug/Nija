import pandas as pd
import pytest

from bot.competitive_profitability_policy import CompetitiveProfitabilityPolicy
from bot.nija_core_loop import CycleSnapshot, NijaCoreLoop


def _df(volume_last_multiplier: float = 1.0) -> pd.DataFrame:
    rows = 120
    frame = pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [100.4] * rows,
            "low": [99.6] * rows,
            "close": [100.0] * rows,
            "volume": [1000.0] * rows,
        }
    )
    frame.loc[rows - 1, "volume"] = 1000.0 * volume_last_multiplier
    return frame


def test_competitive_policy_builds_atr_based_exits_and_risk_size() -> None:
    policy = CompetitiveProfitabilityPolicy()

    profile = policy.profile_entry(_df(volume_last_multiplier=1.0), side="long")

    assert profile.liquidity_ok is True
    assert 0.005 <= profile.risk_fraction <= 0.05
    assert profile.stop_loss_pct > 0
    assert profile.trailing_stop_pct > 0
    assert profile.take_profit_pct[0] < profile.take_profit_pct[1] < profile.take_profit_pct[2]


def test_competitive_policy_blocks_thin_liquidity() -> None:
    policy = CompetitiveProfitabilityPolicy()

    profile = policy.profile_entry(_df(volume_last_multiplier=0.05), side="long")

    assert profile.liquidity_ok is False
    assert "rel_volume" in profile.liquidity_reason


def test_forced_fallback_uses_competitive_policy_for_exits_and_trailing_stop() -> None:
    class Apex:
        def _get_broker_name(self):
            return "coinbase"

    loop = NijaCoreLoop(Apex(), max_positions=1)
    analysis = loop._build_forced_fallback_entry_analysis(
        df=_df(volume_last_multiplier=1.0),
        sig=type("Sig", (), {"reason": "test"})(),
        snapshot=CycleSnapshot(balance=100.0, current_regime="normal", daily_pnl_usd=0.0, open_positions=0),
        action="enter_long",
    )

    assert analysis["competitive_profitability_policy"] is True
    assert analysis["trailing_stop_pct"] > 0
    assert analysis["stop_loss"] < analysis["entry_price"]
    assert analysis["take_profit"][0] > analysis["entry_price"]


def test_forced_fallback_rejects_illiquid_competitive_profile() -> None:
    class Apex:
        def _get_broker_name(self):
            return "coinbase"

    loop = NijaCoreLoop(Apex(), max_positions=1)
    with pytest.raises(ValueError, match="illiquid fallback entry"):
        loop._build_forced_fallback_entry_analysis(
            df=_df(volume_last_multiplier=0.05),
            sig=type("Sig", (), {"reason": "test"})(),
            snapshot=CycleSnapshot(balance=100.0, current_regime="normal", daily_pnl_usd=0.0, open_positions=0),
            action="enter_long",
        )
