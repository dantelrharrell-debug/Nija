from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_software_stop_uses_existing_hard_loss_policy_source():
    row = v371._ensure_software_targets({
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "side": "long",
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1",),
    })
    assert row["risk_stop_loss_source"] == "existing_nija_hard_loss_policy"
