from __future__ import annotations

import pytest

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_existing_explicit_stop_and_take_profit_values_are_preserved(monkeypatch):
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    row = {
        "symbol": "ETH-USD",
        "quantity": 0.1,
        "entry_price": 2500.0,
        "cost_basis_usd": 250.0,
        "side": "long",
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1",),
        "stop_loss": 2450.0,
        "take_profit_1": 2525.0,
        "take_profit_2": 2550.0,
        "take_profit_3": 2600.0,
    }

    protected = v371._ensure_software_targets(row)

    assert protected["stop_loss"] == pytest.approx(2450.0)
    assert protected["take_profit_1"] == pytest.approx(2525.0)
    assert protected["take_profit_2"] == pytest.approx(2550.0)
    assert protected["take_profit_3"] == pytest.approx(2600.0)
    assert protected["software_protection_targets_complete"] is True
