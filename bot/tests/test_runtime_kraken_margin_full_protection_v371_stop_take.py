from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_stop_and_take_profit_are_both_present_for_authenticated_margin_row():
    row = v371._ensure_software_targets({
        "symbol": "ETH-USD",
        "quantity": 0.13742703,
        "entry_price": 2498.6764976293243,
        "cost_basis_usd": 343.38569,
        "side": "long",
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1", "POS2", "POS3", "POS4", "POS5", "POS6"),
    })
    assert row["stop_loss"] > 0
    assert row["take_profit_1"] > row["entry_price"]
    assert row["software_protection_targets_complete"] is True
