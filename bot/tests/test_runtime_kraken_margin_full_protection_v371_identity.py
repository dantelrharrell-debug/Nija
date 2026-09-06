from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_position_id_csv_normalizes_to_authenticated_identity_tuple():
    row = {
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "position_ids": (),
        "position_id": "POS2,POS1,POS2",
    }

    protected = v371._ensure_software_targets(row)

    assert protected["position_ids"] == ("POS1", "POS2")
    assert protected["position_id"] == "POS1,POS2"
    assert protected["software_protection_identity_verified"] is True
