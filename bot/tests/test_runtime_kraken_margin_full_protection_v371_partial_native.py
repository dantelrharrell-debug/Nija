from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_partial_native_components_do_not_override_missing_full_protection_flags():
    row = {
        "account": "platform:kraken",
        "broker": "kraken",
        "symbol": "ETH-USD",
        "quantity": 0.13742703,
        "entry_price": 2498.6764976293243,
        "cost_basis_usd": 343.38569,
        "side": "long",
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1", "POS2"),
        "native_stop_loss_verified": False,
        "native_take_profit_verified": False,
        "native_stop_loss_quantity": 0.05,
        "native_take_profit_quantity": 0.05,
        "software_exit_monitor_verified": False,
    }

    protected = v371._ensure_software_targets(row)

    assert protected["software_protection_identity_verified"] is True
    assert protected["native_stop_loss_verified"] is False
    assert protected["native_take_profit_verified"] is False
