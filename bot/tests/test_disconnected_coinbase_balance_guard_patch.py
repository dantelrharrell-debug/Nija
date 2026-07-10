from __future__ import annotations

from types import SimpleNamespace

from bot import disconnected_coinbase_balance_guard_patch as patch


class CoinbaseBroker:
    def __init__(self, *, connected=False, client=None):
        self.connected = connected
        self.client = client
        self.detail_calls = 0
        self.public_calls = 0
        self._balance_cache = None
        self._balance_cache_time = 0.0
        self._last_known_balance = 99.0

    def _get_account_balance_detailed(self, verbose=False):
        self.detail_calls += 1
        return {"trading_balance": 12.5, "total_funds": 12.5}

    def get_account_balance(self):
        self.public_calls += 1
        return 12.5


class CoinbaseBrokerAdapter:
    def get_account_balance(self):
        return {"USD": 8.0, "USDC": 2.0}


def test_disconnected_coinbase_does_not_dereference_missing_client():
    module = SimpleNamespace(__name__="bot.broker_manager", CoinbaseBroker=CoinbaseBroker)
    assert patch._patch_module(module) is True

    broker = module.CoinbaseBroker(connected=False, client=None)
    detail = broker._get_account_balance_detailed()

    assert detail["trading_balance"] == 0.0
    assert detail["total_funds"] == 0.0
    assert detail["crypto"] == {}
    assert broker.get_account_balance() == 0.0
    assert broker.detail_calls == 0
    assert broker.public_calls == 0
    assert broker._last_known_balance == 0.0


def test_connected_coinbase_delegates_to_original_methods():
    module = SimpleNamespace(__name__="bot.broker_manager", CoinbaseBroker=CoinbaseBroker)
    patch._patch_module(module)

    broker = module.CoinbaseBroker(connected=True, client=object())
    assert broker._get_account_balance_detailed()["trading_balance"] == 12.5
    assert broker.get_account_balance() == 12.5
    assert broker.detail_calls == 1
    assert broker.public_calls == 1


def test_coinbase_adapter_contract_is_not_patched():
    module = SimpleNamespace(__name__="bot.broker_integration", CoinbaseBrokerAdapter=CoinbaseBrokerAdapter)
    assert patch._patch_module(module) is False
    assert module.CoinbaseBrokerAdapter().get_account_balance() == {"USD": 8.0, "USDC": 2.0}
