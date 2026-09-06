from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_full_software_target_helper_marks_complete_targets():
    row = v371._ensure_software_targets({
        "symbol": "ETH-USD",
        "quantity": 0.13742703,
        "entry_price": 2498.6764976293243,
        "cost_basis_usd": 343.38569,
        "side": "long",
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1",),
    })

    assert row["software_stop_loss_available"] is True
    assert row["software_take_profit_available"] is True
    assert row["software_protection_targets_complete"] is True
