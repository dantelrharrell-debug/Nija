from bot.kraken_verified_cost_basis_recovery_patch import _base_from_pair, _reconstruct


def test_pair_normalization():
    assert _base_from_pair("XXBTZUSD") == "XBT"
    assert _base_from_pair("AAVEUSD") == "AAVE"
    assert _base_from_pair("AVAX/USDT") == "AVAX"


def test_weighted_cost_survives_partial_sell():
    trades = {
        "1": {"time": 1, "pair": "AAVEUSD", "type": "buy", "vol": "1", "price": "50", "cost": "50", "fee": "0.50"},
        "2": {"time": 2, "pair": "AAVEUSD", "type": "buy", "vol": "1", "price": "70", "cost": "70", "fee": "0.70"},
        "3": {"time": 3, "pair": "AAVEUSD", "type": "sell", "vol": "0.5", "price": "90", "cost": "45", "fee": "0.45"},
    }
    qty, avg = _reconstruct(trades)["AAVE"]
    assert round(qty, 8) == 1.5
    assert round(avg, 2) == 60.60


def test_sells_cannot_create_negative_inventory():
    trades = {
        "1": {"time": 1, "pair": "CELOUSD", "type": "sell", "vol": "10", "price": "1", "cost": "10", "fee": "0.1"},
    }
    assert "CELO" not in _reconstruct(trades)
