from bot.runtime_kraken_terminal_symbol_canonicalization_v261_patch import (
    _canonical_terminal_symbol,
    _self_test,
)


def test_known_legacy_kraken_pair_ids_canonicalize():
    assert _canonical_terminal_symbol("XETHZUSD") == "ETH-USD"
    assert _canonical_terminal_symbol("XETHZ-USD") == "ETH-USD"
    assert _canonical_terminal_symbol("XXBTZUSD") == "BTC-USD"
    assert _canonical_terminal_symbol("XXRPZUSD") == "XRP-USD"


def test_canonical_and_unknown_symbols_are_not_rewritten():
    assert _canonical_terminal_symbol("ETH-USD") == "ETH-USD"
    assert _canonical_terminal_symbol("SOLUSD") == "SOLUSD"
    assert _canonical_terminal_symbol("") == ""


def test_v261_self_test():
    assert _self_test() is True
