from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_authenticated_position_marks_identity_true():
    row = v371._ensure_software_targets({
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "position_ids": ("POS1",),
    })
    assert row["software_protection_identity_verified"] is True
