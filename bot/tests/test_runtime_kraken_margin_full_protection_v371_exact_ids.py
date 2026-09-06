from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_exact_margin_position_ids_are_retained_for_protection():
    ids = ("A", "B", "C")
    row = v371._ensure_software_targets({
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ids,
    })
    assert row["protection_position_ids"] == ids
