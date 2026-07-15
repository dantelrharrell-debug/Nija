from __future__ import annotations

import os
from types import SimpleNamespace

from bot.okx_funding_wallet_readiness_patch import _publish, _stable_sum


class AccountAPI:
    def __init__(self, spendable: float, total: float | None = None):
        self.spendable = spendable
        self.total = spendable if total is None else total

    def get_balance(self):
        return {
            "code": "0",
            "data": [{
                "totalEq": str(self.total),
                "details": [{"ccy": "USDT", "availBal": str(self.spendable), "cashBal": str(self.total)}],
            }],
        }


class AssetAPI:
    def __init__(self, spendable: float, total: float | None = None):
        self.spendable = spendable
        self.total = spendable if total is None else total

    def get_balances(self, ccy=None):
        return {
            "code": "0",
            "data": [{"ccy": "USDT", "availBal": str(self.spendable), "bal": str(self.total)}],
        }


def test_stable_sum_ignores_non_stable_assets():
    spendable, total = _stable_sum([
        {"ccy": "USDT", "availBal": "10", "bal": "11"},
        {"ccy": "BTC", "availBal": "2", "bal": "2"},
    ], funding=True)
    assert spendable == 10.0
    assert total == 11.0


def test_funding_capital_is_visible_but_not_trading_ready(monkeypatch):
    monkeypatch.setenv("OKX_MIN_ORDER_USD", "10")
    broker = SimpleNamespace(account_api=AccountAPI(0), asset_api=AssetAPI(146.26))
    _publish(broker)
    assert os.environ["NIJA_OKX_BALANCE_OBSERVED"] == "1"
    assert os.environ["NIJA_OKX_FUNDING_STATUS"] == "funded_needs_transfer"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "0"
    assert float(os.environ["NIJA_OKX_FUNDING_SPENDABLE_QUOTE"]) == 146.26
    assert float(os.environ["NIJA_OKX_SPENDABLE_QUOTE"]) == 0.0


def test_trading_wallet_capital_is_ready(monkeypatch):
    monkeypatch.setenv("OKX_MIN_ORDER_USD", "10")
    broker = SimpleNamespace(account_api=AccountAPI(25), asset_api=AssetAPI(121.26))
    _publish(broker)
    assert os.environ["NIJA_OKX_FUNDING_STATUS"] == "funded"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "1"
    assert float(os.environ["NIJA_OKX_SPENDABLE_QUOTE"]) == 25.0
    assert float(os.environ["NIJA_OKX_TOTAL_OBSERVED_QUOTE"]) == 146.26


def test_auth_failure_is_unobserved_not_underfunded(monkeypatch):
    class Broken:
        def get_balance(self):
            raise RuntimeError("invalid key")

        def _request(self, *args, **kwargs):
            return {"code": "50111", "data": []}

    broker = SimpleNamespace(account_api=Broken())
    _publish(broker)
    assert os.environ["NIJA_OKX_BALANCE_OBSERVED"] == "0"
    assert os.environ["NIJA_OKX_FUNDING_STATUS"] == "unobserved"
    assert os.environ["NIJA_OKX_TRADING_READY"] == "0"
    assert os.environ["NIJA_OKX_SPENDABLE_QUOTE"] == "unknown"
