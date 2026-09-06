from __future__ import annotations

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


def test_non_margin_rows_are_not_rewritten():
    row = {"symbol": "ETH-USD", "quantity": 1.0, "entry_price": 2500.0}
    assert v371._ensure_software_targets(row) == row
