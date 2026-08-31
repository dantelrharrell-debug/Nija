from __future__ import annotations

from types import SimpleNamespace


def test_extract_price_accepts_numeric_and_quote_fields():
    from bot import runtime_exit_market_price_convergence_v333_patch as v333

    assert v333._extract_price(123.45) == 123.45
    assert v333._extract_price({"last_price": "2466.50"}) == 2466.50
    assert v333._extract_price({"bid": "100", "ask": "102"}) == 101.0
    assert v333._extract_price({"price": 0}) == 0.0


def test_price_patch_falls_back_to_canonical_get_current_price(monkeypatch):
    from bot import auto_exit_sl_tp_runtime_patch as auto_exit
    from bot import runtime_exit_market_price_convergence_v333_patch as v333

    original = auto_exit._price
    monkeypatch.setattr(auto_exit, "_price", lambda broker, symbol: 0.0)
    broker = SimpleNamespace(
        broker_type="coinbase",
        get_current_price=lambda symbol: 2467.25,
    )
    assert v333._patch_price() is True
    assert auto_exit._price(broker, "ETH-USD") == 2467.25
    monkeypatch.setattr(auto_exit, "_price", original)


def test_price_patch_never_reuses_entry_price(monkeypatch):
    from bot import auto_exit_sl_tp_runtime_patch as auto_exit
    from bot import runtime_exit_market_price_convergence_v333_patch as v333

    original = auto_exit._price
    monkeypatch.setattr(auto_exit, "_price", lambda broker, symbol: 0.0)
    broker = SimpleNamespace(broker_type="kraken")
    assert v333._patch_price() is True
    assert auto_exit._price(broker, "ETH-USD") == 0.0
    monkeypatch.setattr(auto_exit, "_price", original)
