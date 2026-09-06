from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_target_completeness_requires_identity():
    row = v371._ensure_software_targets({
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "position_ids": (),
    })
    assert row["software_protection_targets_complete"] is False
