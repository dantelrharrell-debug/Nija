import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from bot.nija_core_loop import _cached_broker_balances_for_log


class _BrokerType:
    value = "coinbase"


def test_cached_broker_balances_for_log_does_not_call_exchange_balance_api() -> None:
    broker = SimpleNamespace(
        connected=True,
        _last_known_balance=42.5,
        get_account_balance=Mock(side_effect=AssertionError("live API call not allowed")),
    )
    manager = SimpleNamespace(brokers={_BrokerType(): broker})

    snapshot = _cached_broker_balances_for_log(manager)

    assert snapshot == {
        "coinbase": {"balance": 42.5, "connected": True, "source": "cached"}
    }
    broker.get_account_balance.assert_not_called()


def test_kraken_user_configs_are_independent_not_copy_trading() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    retail_users = json.loads((repo_root / "config/users/retail_kraken.json").read_text())
    individual_users = [
        json.loads((repo_root / "config/users/daivon_frazier.json").read_text()),
        json.loads((repo_root / "config/users/tania_gilbert.json").read_text()),
    ]

    for user in [*retail_users, *individual_users]:
        assert user["enabled"] is True
        assert user["active_trading"] is True
        assert user["independent_trading"] is True
        assert user["copy_from_platform"] is False
