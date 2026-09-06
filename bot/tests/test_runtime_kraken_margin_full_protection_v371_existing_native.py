from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_existing_native_flags_remain_visible_after_target_enrichment():
    row = v371._ensure_software_targets({
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1",),
        "native_stop_loss_verified": False,
        "native_take_profit_verified": False,
    })
    assert row["native_stop_loss_verified"] is False
    assert row["native_take_profit_verified"] is False
