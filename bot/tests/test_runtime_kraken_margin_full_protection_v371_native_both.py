from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_helper_preserves_native_verification_fields():
    row = {
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1",),
        "native_stop_loss_verified": True,
        "native_take_profit_verified": True,
    }
    protected = v371._ensure_software_targets(row)
    assert protected["native_stop_loss_verified"] is True
    assert protected["native_take_profit_verified"] is True
